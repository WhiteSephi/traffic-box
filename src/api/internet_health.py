"""Multi-stage internet quality, Dual-Stack HTTPS canary, and Zombie-WAN diagnostics."""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import math
import socket
import threading
import time
from typing import Callable

from src.api.models import HealthStatus, InternetHealthSnapshot
from src.api.net_health import (
    DnsQueryResult,
    HttpsCanaryResult,
    detect_active_os_dns,
    has_global_ipv6,
    measure_https_canary,
    measure_ping,
    measure_uncached_dns,
)
from src.api.upnp_client import detect_default_gateway


@dataclass(frozen=True)
class CanarySpec:
    """HTTPS 204 canary endpoint specification resolved and IP-cached in memory."""

    name: str
    host: str
    path: str = "/generate_204"
    expected_statuses: tuple[int, ...] = (204,)


@dataclass(frozen=True)
class DirectIpCanarySpec:
    """Direct-IP HTTPS fallback specification used only during cold-start DNS outage."""

    name: str
    ipv4: str
    ipv6: str
    path: str
    expected_statuses: tuple[int, ...] = (200,)


DEFAULT_HOST_CANARIES: tuple[CanarySpec, ...] = (
    CanarySpec("Cloudflare", "cp.cloudflare.com", "/generate_204", (204,)),
    CanarySpec("Google", "connectivitycheck.gstatic.com", "/generate_204", (204,)),
)

DEFAULT_DIRECT_IP_CANARIES: tuple[DirectIpCanarySpec, ...] = (
    DirectIpCanarySpec("Cloudflare", "1.1.1.1", "2606:4700:4700::1111", "/cdn-cgi/trace", (200,)),
    DirectIpCanarySpec("Google", "8.8.8.8", "2001:4860:4860::8888", "/resolve?name=.&type=NS", (200,)),
)


class SlidingWindowTracker:
    """Fixed-size sliding window computing packet loss, median, p95, and jitter."""

    def __init__(self, window_size: int = 60) -> None:
        self._window_size = max(5, int(window_size))
        self._samples: deque[float | None] = deque(maxlen=self._window_size)

    def record(self, ping_ms: float | None) -> None:
        """Append one ping measurement (float ms or None for timeout/loss)."""
        if ping_ms is not None:
            self._samples.append(max(0.0, float(ping_ms)))
        else:
            self._samples.append(None)

    def has_any_success(self) -> bool:
        """Return True if at least one successful ping exists in the window."""
        return any(v is not None for v in self._samples)

    def stats(self) -> tuple[int, int, float, float | None, float | None, float, int]:
        """Return (total, losses, loss_pct, median_ms, p95_ms, jitter_ms, consecutive_losses)."""
        total = len(self._samples)
        if total == 0:
            return 0, 0, 0.0, None, None, 0.0, 0

        valid: list[float] = []
        losses = 0
        diffs: list[float] = []
        prev_valid: float | None = None

        for item in self._samples:
            if item is None:
                losses += 1
                prev_valid = None
            else:
                valid.append(item)
                if prev_valid is not None:
                    diffs.append(abs(item - prev_valid))
                prev_valid = item

        consecutive_losses = 0
        for item in reversed(self._samples):
            if item is None:
                consecutive_losses += 1
            else:
                break

        loss_pct = (losses / total) * 100.0
        if not valid:
            return total, losses, loss_pct, None, None, 0.0, consecutive_losses

        sorted_v = sorted(valid)
        n = len(sorted_v)
        mid = n // 2
        if n % 2 == 1:
            median_ms = sorted_v[mid]
        else:
            median_ms = (sorted_v[mid - 1] + sorted_v[mid]) / 2.0

        p95_idx = min(n - 1, max(0, int(math.ceil(0.95 * n)) - 1))
        p95_ms = sorted_v[p95_idx]
        jitter_ms = (sum(diffs) / len(diffs)) if diffs else 0.0

        return (
            total,
            losses,
            round(loss_pct, 1),
            round(median_ms, 2),
            round(p95_ms, 2),
            round(jitter_ms, 2),
            consecutive_losses,
        )

    def clear(self) -> None:
        """Clear all recorded samples."""
        self._samples.clear()


class BaselineTracker:
    """Learns idle connection baseline RTT & jitter while guarding against bufferbloat."""

    IDLE_UTIL_MAX = 0.40

    def __init__(self, min_samples: int = 15) -> None:
        self.min_samples = max(5, int(min_samples))
        self.baseline_rtt_ms: float | None = None
        self.baseline_jitter_ms: float | None = None
        self._sample_count: int = 0

    @property
    def is_ready(self) -> bool:
        """Return True once enough clean idle samples have been collected."""
        return self._sample_count >= self.min_samples and self.baseline_rtt_ms is not None

    def update(
        self,
        median_ms: float | None,
        jitter_ms: float,
        *,
        is_healthy: bool,
        line_utilization: float,
    ) -> None:
        """Update idle baseline using EMA only during healthy, low-utilization periods."""
        if not is_healthy or median_ms is None or line_utilization >= self.IDLE_UTIL_MAX:
            return

        self._sample_count += 1
        clean_jitter = max(0.0, jitter_ms)
        if self.baseline_rtt_ms is None or self.baseline_jitter_ms is None:
            self.baseline_rtt_ms = round(median_ms, 2)
            self.baseline_jitter_ms = round(clean_jitter, 2)
            return

        alpha = 0.20 if self._sample_count <= self.min_samples else 0.08
        self.baseline_rtt_ms = round(self.baseline_rtt_ms * (1.0 - alpha) + median_ms * alpha, 2)
        self.baseline_jitter_ms = round(self.baseline_jitter_ms * (1.0 - alpha) + clean_jitter * alpha, 2)

    def p95_warn_threshold(self) -> float | None:
        """Return latency warning threshold with an absolute floor to avoid tiny-ping false positives."""
        if not self.is_ready or self.baseline_rtt_ms is None:
            return None
        return max(self.baseline_rtt_ms * 2.5, self.baseline_rtt_ms + 25.0, 50.0)

    def jitter_warn_threshold(self) -> float | None:
        """Return jitter warning threshold with a 15 ms absolute floor."""
        if not self.is_ready or self.baseline_jitter_ms is None:
            return None
        return max(self.baseline_jitter_ms * 2.5, 15.0)

    def reset(self) -> None:
        """Reset learned baseline."""
        self.baseline_rtt_ms = None
        self.baseline_jitter_ms = None
        self._sample_count = 0


def _format_dns_error(error_code: str) -> str:
    """Format a human-readable German label for a DNS error code."""
    mapping = {
        "timeout": "Timeout",
        "servfail": "SERVFAIL",
        "refused": "REFUSED",
        "formerr": "FORMERR",
        "hijacked": "Umleitung/Hijack",
        "invalid_reply": "Ungültige Antwort",
        "no_dns_server": "Kein DNS erkannt",
        "socket_error": "Socket-Fehler",
    }
    return mapping.get(error_code, error_code or "Fehler")


class HealthEvaluator:
    """Deterministic five-state classifier with provider quorum and anti-flap hysteresis."""

    CONFIRM_THRESHOLD: int = 2
    DNS_WARN_MS: float = 200.0
    LAN_LOSS_ERR_PCT: float = 10.0
    WAN_LOSS_OFFLINE_PCT: float = 20.0
    WAN_LOSS_DEGRADED_MIN_DROPS: int = 2

    def __init__(self) -> None:
        self._committed: HealthStatus = HealthStatus.UNKNOWN
        self._pending_status: HealthStatus | None = None
        self._pending_count: int = 0
        self._committed_tag: str = "Prüfe…"
        self._committed_reason: str = "Erste Verbindungsprüfung läuft…"

    @property
    def committed_status(self) -> HealthStatus:
        """Return the currently committed (hysteresis-filtered) health status."""
        return self._committed

    def reset(self) -> None:
        """Reset hysteresis state."""
        self._committed = HealthStatus.UNKNOWN
        self._pending_status = None
        self._pending_count = 0
        self._committed_tag = "Prüfe…"
        self._committed_reason = "Erste Verbindungsprüfung läuft…"

    def evaluate(
        self,
        *,
        probe_count: int,
        box_reachable: bool,
        physical_link_up: bool,
        wan_connected: bool,
        is_local_fallback: bool,
        gateway_ip: str,
        lan_ping_ms: float | None,
        lan_loss_pct: float,
        lan_consecutive_fails: int,
        lan_ok: bool,
        ipv4_ok_count: int,
        ipv4_total: int,
        ipv4_ms: float | None,
        ipv6_available: bool,
        ipv6_ok_count: int,
        ipv6_total: int,
        ipv6_ms: float | None,
        ip_mode: str,
        captive_portal_detected: bool,
        dns_enabled: bool,
        dns_ip: str,
        dns_ok: bool | None,
        dns_ms: float | None,
        dns_rcode: int | None,
        dns_error: str,
        wan_samples: int,
        wan_loss_count: int,
        wan_loss_pct: float,
        wan_median_ms: float | None,
        wan_p95_ms: float | None,
        wan_jitter_ms: float,
        baseline_rtt_ms: float | None,
        baseline_jitter_ms: float | None,
        baseline_ready: bool,
        p95_thresh: float | None,
        jitter_thresh: float | None,
        is_line_saturated: bool,
        last_probe_ts: float,
        advance_hysteresis: bool = True,
    ) -> InternetHealthSnapshot:
        """Classify current network measurements into a HealthStatus with hysteresis."""
        ipv4_alive: bool | None = (ipv4_ok_count >= 1) if ipv4_total > 0 else None
        ipv6_checked = (ip_mode == "dual_stack") or (ip_mode == "auto" and ipv6_available)
        ipv6_alive: bool | None = (ipv6_ok_count >= 1) if (ipv6_checked and ipv6_total > 0) else None

        candidate, cand_tag, cand_reason, immediate = self._classify_candidate(
            probe_count=probe_count,
            box_reachable=box_reachable,
            physical_link_up=physical_link_up,
            wan_connected=wan_connected,
            is_local_fallback=is_local_fallback,
            gateway_ip=gateway_ip,
            lan_loss_pct=lan_loss_pct,
            lan_consecutive_fails=lan_consecutive_fails,
            lan_ok=lan_ok,
            ipv4_alive=ipv4_alive,
            ipv4_total=ipv4_total,
            ipv6_checked=ipv6_checked,
            ipv6_alive=ipv6_alive,
            ipv6_total=ipv6_total,
            captive_portal_detected=captive_portal_detected,
            dns_enabled=dns_enabled,
            dns_ip=dns_ip,
            dns_ok=dns_ok,
            dns_ms=dns_ms,
            dns_error=dns_error,
            wan_samples=wan_samples,
            wan_loss_count=wan_loss_count,
            wan_loss_pct=wan_loss_pct,
            wan_p95_ms=wan_p95_ms,
            wan_jitter_ms=wan_jitter_ms,
            baseline_rtt_ms=baseline_rtt_ms,
            baseline_jitter_ms=baseline_jitter_ms,
            baseline_ready=baseline_ready,
            p95_thresh=p95_thresh,
            jitter_thresh=jitter_thresh,
            is_line_saturated=is_line_saturated,
        )

        if candidate != HealthStatus.UNKNOWN:
            if immediate or self._committed == HealthStatus.UNKNOWN:
                self._committed = candidate
                self._committed_tag = cand_tag
                self._committed_reason = cand_reason
                self._pending_status = None
                self._pending_count = 0
            elif advance_hysteresis:
                if candidate == self._committed:
                    self._pending_status = None
                    self._pending_count = 0
                    self._committed_tag = cand_tag
                    self._committed_reason = cand_reason
                else:
                    if candidate == self._pending_status:
                        self._pending_count += 1
                    else:
                        self._pending_status = candidate
                        self._pending_count = 1
                    if self._pending_count >= self.CONFIRM_THRESHOLD:
                        self._committed = candidate
                        self._committed_tag = cand_tag
                        self._committed_reason = cand_reason
                        self._pending_status = None
                        self._pending_count = 0

        in_burst = (
            self._pending_status is not None
            or self._committed not in (HealthStatus.STABLE, HealthStatus.UNKNOWN)
        )

        return InternetHealthSnapshot(
            status=self._committed,
            reason=self._committed_reason,
            short_tag=self._committed_tag,
            gateway_ip=gateway_ip,
            lan_ping_ms=lan_ping_ms,
            lan_loss_pct=lan_loss_pct,
            lan_ok=lan_ok,
            ipv4_ok=ipv4_alive,
            ipv4_quorum=(ipv4_ok_count, ipv4_total),
            ipv4_ms=ipv4_ms,
            ipv6_available=ipv6_available,
            ipv6_ok=ipv6_alive,
            ipv6_quorum=(ipv6_ok_count, ipv6_total),
            ipv6_ms=ipv6_ms,
            captive_portal_detected=captive_portal_detected,
            dns_ip=dns_ip,
            dns_ok=dns_ok,
            dns_ms=dns_ms,
            dns_rcode=dns_rcode,
            dns_error=dns_error,
            wan_loss_pct=wan_loss_pct,
            wan_median_ms=wan_median_ms,
            wan_p95_ms=wan_p95_ms,
            wan_jitter_ms=wan_jitter_ms,
            baseline_rtt_ms=baseline_rtt_ms,
            baseline_jitter_ms=baseline_jitter_ms,
            baseline_ready=baseline_ready,
            is_line_saturated=is_line_saturated,
            in_burst_mode=in_burst,
            probe_count=probe_count,
            last_probe_ts=last_probe_ts,
        )

    def _classify_candidate(
        self,
        *,
        probe_count: int,
        box_reachable: bool,
        physical_link_up: bool,
        wan_connected: bool,
        is_local_fallback: bool,
        gateway_ip: str,
        lan_loss_pct: float,
        lan_consecutive_fails: int,
        lan_ok: bool,
        ipv4_alive: bool | None,
        ipv4_total: int,
        ipv6_checked: bool,
        ipv6_alive: bool | None,
        ipv6_total: int,
        captive_portal_detected: bool,
        dns_enabled: bool,
        dns_ip: str,
        dns_ok: bool | None,
        dns_ms: float | None,
        dns_error: str,
        wan_samples: int,
        wan_loss_count: int,
        wan_loss_pct: float,
        wan_p95_ms: float | None,
        wan_jitter_ms: float,
        baseline_rtt_ms: float | None,
        baseline_jitter_ms: float | None,
        baseline_ready: bool,
        p95_thresh: float | None,
        jitter_thresh: float | None,
        is_line_saturated: bool,
    ) -> tuple[HealthStatus, str, str, bool]:
        """Determine candidate status without hysteresis. Returns (status, tag, reason, immediate)."""
        # Authoritative FRITZ!Box link down states apply immediately
        if box_reachable and not is_local_fallback:
            if not physical_link_up:
                return (
                    HealthStatus.OFFLINE,
                    "Kein Sync",
                    "Kein DSL-/WAN-Sync an der FRITZ!Box",
                    True,
                )
            if not wan_connected:
                return (
                    HealthStatus.OFFLINE,
                    "Kein Internet",
                    "FRITZ!Box meldet keine Internetverbindung",
                    True,
                )

        if probe_count <= 0:
            return HealthStatus.UNKNOWN, "Prüfe…", "Erste Verbindungsprüfung läuft…", False

        # 1. LAN / Router Problem
        lan_unreachable = (
            not lan_ok
            or (gateway_ip and lan_consecutive_fails >= 2)
            or (not box_reachable and not is_local_fallback and not gateway_ip)
        )
        if lan_unreachable:
            gw_hint = f" ({gateway_ip})" if gateway_ip else ""
            return (
                HealthStatus.LAN_ERROR,
                "LAN-Problem",
                f"Router/Gateway{gw_hint} nicht erreichbar – Problem liegt im Heimnetz, nicht beim ISP",
                False,
            )
        if gateway_ip and lan_loss_pct > self.LAN_LOSS_ERR_PCT:
            return (
                HealthStatus.LAN_ERROR,
                "LAN-Verlust",
                f"Paketverlust zum Gateway ({lan_loss_pct:.0f} %) – Problem liegt im Heimnetz",
                False,
            )

        # 2. Offline / Zombie-WAN
        internet_quorum_failed = (
            (ipv4_total > 0 and ipv4_alive is False and ipv6_alive is not True)
            or (ipv6_total > 0 and ipv6_alive is False and ipv4_alive is not True)
        )
        severe_wan_loss = wan_samples >= 10 and wan_loss_pct > self.WAN_LOSS_OFFLINE_PCT

        if internet_quorum_failed or severe_wan_loss:
            is_zombie = box_reachable and not is_local_fallback and wan_connected
            if is_zombie:
                if captive_portal_detected:
                    reason = "Captive Portal / Umleitung blockiert Internet trotz FRITZ!Box-Sync"
                elif severe_wan_loss and not internet_quorum_failed:
                    reason = f"WAN hängt trotz FRITZ!Box-Sync (> {wan_loss_pct:.0f} % Paketverlust)"
                else:
                    reason = "WAN hängt trotz FRITZ!Box-Sync! Router meldet Verbunden, aber kein Internetverkehr möglich."
                return HealthStatus.ZOMBIE_WAN, "Zombie-WAN", reason, False

            if captive_portal_detected:
                return (
                    HealthStatus.OFFLINE,
                    "Captive Portal",
                    "Captive Portal / HTTP-Umleitung erkannt – kein freier Internetzugang",
                    False,
                )
            if severe_wan_loss and not internet_quorum_failed:
                return (
                    HealthStatus.OFFLINE,
                    "Offline",
                    f"Massiver Paketverlust ({wan_loss_pct:.0f} % > 20 %)",
                    False,
                )
            return (
                HealthStatus.OFFLINE,
                "Offline",
                "Keine Internetverbindung (alle unabhängigen HTTPS-Probes fehlgeschlagen)",
                False,
            )

        # 3. Local DNS Error (HTTPS reachable via cached/direct IP, uncached DNS broken)
        any_https_ok = (ipv4_alive is True) or (ipv6_alive is True)
        if dns_enabled and any_https_ok and dns_ok is False:
            err_label = _format_dns_error(dns_error)
            dns_target = dns_ip or "System-DNS"
            return (
                HealthStatus.DNS_ERROR,
                "DNS-Störung",
                f"Lokaler DNS ({dns_target}) gestört ({err_label}) – Internet über IP erreichbar",
                False,
            )

        # 4. Degraded Quality
        tags: list[str] = []
        reasons: list[str] = []
        has_latency_or_jitter = False

        if ipv6_checked and ipv4_total > 0 and ipv6_total > 0:
            if ipv4_alive is False and ipv6_alive is True:
                tags.append("Nur IPv6")
                reasons.append("IPv4 gestört (nur IPv6)")
            elif ipv4_alive is True and ipv6_alive is False:
                tags.append("Nur IPv4")
                reasons.append("IPv6 gestört (nur IPv4)")

        if wan_samples >= 10 and wan_loss_count >= self.WAN_LOSS_DEGRADED_MIN_DROPS and wan_loss_pct <= self.WAN_LOSS_OFFLINE_PCT:
            tags.append(f"Verlust {wan_loss_pct:.0f}%")
            reasons.append(f"Paketverlust {wan_loss_pct:.0f} %")

        if dns_enabled and dns_ok is True and dns_ms is not None and dns_ms > self.DNS_WARN_MS:
            tags.append("DNS langsam")
            reasons.append(f"DNS langsam ({dns_ms:.0f} ms)")

        if baseline_ready and p95_thresh is not None and wan_p95_ms is not None and wan_p95_ms > p95_thresh:
            tags.append("Hoher Ping")
            reasons.append("Hohe Latenz")
            has_latency_or_jitter = True

        if baseline_ready and jitter_thresh is not None and wan_jitter_ms > jitter_thresh:
            tags.append("Hoher Jitter")
            reasons.append("Hoher Jitter")
            has_latency_or_jitter = True

        if tags:
            reason_str = ", ".join(reasons)
            if is_line_saturated and has_latency_or_jitter:
                reason_str += " (Leitung ausgelastet)"
            return (
                HealthStatus.DEGRADED,
                tags[0],
                reason_str,
                False,
            )

        # 5. Stable
        return HealthStatus.STABLE, "Stabil", "Alles normal", False


def _default_resolve_host(host: str, family: int) -> str:
    """Resolve host to an IPv4 or IPv6 address string, or empty string on failure."""
    try:
        infos = socket.getaddrinfo(host, 443, family, socket.SOCK_STREAM)
        for info in infos:
            sockaddr = info[4]
            if sockaddr and isinstance(sockaddr[0], str):
                return sockaddr[0].split("%")[0]
    except OSError:
        pass
    return ""


class InternetHealthMonitor:
    """Non-blocking background orchestrator for multi-stage internet health checks."""

    IP_CACHE_TTL_SEC: float = 900.0
    LINE_SATURATION_THRESHOLD: float = 0.75

    def __init__(
        self,
        *,
        probe_interval_sec: int = 30,
        burst_interval_sec: int = 5,
        ip_mode: str = "auto",
        enable_uncached_dns: bool = True,
        enable_dns_monitor: bool = True,
        host_canaries: tuple[CanarySpec, ...] = DEFAULT_HOST_CANARIES,
        direct_ip_canaries: tuple[DirectIpCanarySpec, ...] = DEFAULT_DIRECT_IP_CANARIES,
        ping_fn: Callable[[str], float | None] = measure_ping,
        dns_fn: Callable[[str], DnsQueryResult] = measure_uncached_dns,
        detect_dns_fn: Callable[[], str] = detect_active_os_dns,
        canary_fn: Callable[..., HttpsCanaryResult] = measure_https_canary,
        ipv6_fn: Callable[[], bool] = has_global_ipv6,
        resolve_fn: Callable[[str, int], str] = _default_resolve_host,
        gateway_fn: Callable[[], str] = detect_default_gateway,
    ) -> None:
        self.probe_interval_sec = max(10, min(120, int(probe_interval_sec)))
        self.burst_interval_sec = max(3, min(30, int(burst_interval_sec)))
        self.ip_mode = ip_mode if ip_mode in ("auto", "ipv4_only", "dual_stack") else "auto"
        self.enable_uncached_dns = bool(enable_uncached_dns)
        self.enable_dns_monitor = bool(enable_dns_monitor)

        self._host_canaries = host_canaries
        self._direct_ip_canaries = direct_ip_canaries

        self._ping_fn = ping_fn
        self._dns_fn = dns_fn
        self._detect_dns_fn = detect_dns_fn
        self._canary_fn = canary_fn
        self._ipv6_fn = ipv6_fn
        self._resolve_fn = resolve_fn
        self._gateway_fn = gateway_fn

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._in_flight = False
        self._probe_thread: threading.Thread | None = None

        self._wan_window = SlidingWindowTracker(window_size=60)
        self._lan_window = SlidingWindowTracker(window_size=12)
        self._baseline = BaselineTracker(min_samples=15)
        self._evaluator = HealthEvaluator()

        self._ip_cache: dict[tuple[str, int], tuple[str, float]] = {}
        self._probe_count: int = 0
        self._last_probe_ts: float = 0.0
        self._last_probe_wall: float = 0.0

        # Latest router & traffic context updated each 1s tick
        self._box_reachable: bool = True
        self._physical_link_up: bool = True
        self._wan_connected: bool = True
        self._is_local_fallback: bool = False
        self._router_host: str = ""
        self._line_utilization: float = 0.0

        # Latest raw probe results from background cycle
        self._gateway_ip: str = ""
        self._lan_ping_ms: float | None = None
        self._lan_ok: bool = True
        self._ipv4_ok_count: int = 0
        self._ipv4_total: int = 0
        self._ipv4_ms: float | None = None
        self._ipv6_available: bool = False
        self._ipv6_ok_count: int = 0
        self._ipv6_total: int = 0
        self._ipv6_ms: float | None = None
        self._captive_portal: bool = False
        self._dns_ip: str = ""
        self._dns_ok: bool | None = None
        self._dns_ms: float | None = None
        self._dns_rcode: int | None = None
        self._dns_error: str = ""

        self._last_snapshot = InternetHealthSnapshot()

    def configure(
        self,
        *,
        probe_interval_sec: int,
        ip_mode: str,
        enable_uncached_dns: bool,
        enable_dns_monitor: bool,
    ) -> None:
        """Update runtime configuration safely without clearing learned history."""
        with self._lock:
            self.probe_interval_sec = max(10, min(120, int(probe_interval_sec)))
            self.ip_mode = ip_mode if ip_mode in ("auto", "ipv4_only", "dual_stack") else "auto"
            self.enable_uncached_dns = bool(enable_uncached_dns)
            self.enable_dns_monitor = bool(enable_dns_monitor)

    def stop(self) -> None:
        """Signal any background probe thread to abort and ignore late results."""
        self._stop_event.set()
        thread = self._probe_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.3)

    def record_tick(
        self,
        ping_ms: float | None,
        *,
        box_reachable: bool,
        physical_link_up: bool,
        wan_connected: bool,
        is_local_fallback: bool,
        router_host: str = "",
        line_utilization: float = 0.0,
        ping_enabled: bool = True,
    ) -> InternetHealthSnapshot:
        """Record a 1s measurement tick and trigger an async background probe if due."""
        now = time.monotonic()
        should_spawn = False

        with self._lock:
            self._box_reachable = box_reachable
            self._physical_link_up = physical_link_up
            self._wan_connected = wan_connected
            self._is_local_fallback = is_local_fallback
            self._router_host = router_host.strip()
            self._line_utilization = max(0.0, min(1.0, float(line_utilization)))

            if ping_enabled:
                self._wan_window.record(ping_ms)

            wan_total, wan_losses, wan_loss_pct, wan_med, wan_p95, wan_jit, wan_consec = self._wan_window.stats()
            if self._evaluator.committed_status == HealthStatus.STABLE and wan_total >= 5:
                self._baseline.update(
                    wan_med,
                    wan_jit,
                    is_healthy=(wan_losses == 0),
                    line_utilization=self._line_utilization,
                )

            snapshot = self._build_snapshot_locked(advance_hysteresis=False)
            self._last_snapshot = snapshot

            if not self._stop_event.is_set() and not self._in_flight:
                elapsed = now - self._last_probe_ts
                is_first = self._probe_count == 0
                fast_trigger = (
                    snapshot.in_burst_mode
                    or (ping_enabled and wan_consec >= 2)
                    or (box_reachable and not is_local_fallback and (not physical_link_up or not wan_connected))
                )
                due_interval = self.burst_interval_sec if fast_trigger else self.probe_interval_sec
                if is_first or elapsed >= due_interval:
                    self._in_flight = True
                    should_spawn = True

        if should_spawn:
            self._probe_thread = threading.Thread(
                target=self._run_background_cycle,
                name="TrafficBoxHealthProbe",
                daemon=True,
            )
            self._probe_thread.start()

        return snapshot

    def get_snapshot(self) -> InternetHealthSnapshot:
        """Return the latest computed InternetHealthSnapshot thread-safely."""
        with self._lock:
            self._last_snapshot = self._build_snapshot_locked(advance_hysteresis=False)
            return self._last_snapshot

    def _run_background_cycle(self) -> None:
        try:
            self.run_probe_cycle()
        except Exception:
            pass
        finally:
            with self._lock:
                self._in_flight = False

    def _resolve_cached_ip(self, host: str, family: int, now_mono: float) -> str:
        """Return cached IP for host+family, refreshing every IP_CACHE_TTL_SEC when needed."""
        key = (host, family)
        with self._lock:
            cached = self._ip_cache.get(key)
        if cached is not None and (now_mono - cached[1]) < self.IP_CACHE_TTL_SEC:
            return cached[0]

        resolved = self._resolve_fn(host, family)
        if resolved:
            with self._lock:
                self._ip_cache[key] = (resolved, now_mono)
            return resolved

        # Keep stale cached IP if DNS just broke so HTTPS checks keep isolating DNS errors
        return cached[0] if cached is not None else ""

    def run_probe_cycle(self) -> InternetHealthSnapshot:
        """Execute one full multi-stage diagnostic cycle (LAN, Dual-Stack HTTPS 204, Uncached DNS)."""
        if self._stop_event.is_set():
            return self.get_snapshot()

        now_mono = time.monotonic()
        with self._lock:
            box_reachable = self._box_reachable
            is_local_fallback = self._is_local_fallback
            router_host = self._router_host
            ip_mode = self.ip_mode
            enable_dns = self.enable_dns_monitor
            enable_uncached = self.enable_uncached_dns

        gateway_ip = ""
        if box_reachable and not is_local_fallback and router_host:
            gateway_ip = router_host
        else:
            gateway_ip = self._gateway_fn() or ""

        ipv6_available = False if ip_mode == "ipv4_only" else bool(self._ipv6_fn())
        test_ipv6 = (ip_mode == "dual_stack") or (ip_mode == "auto" and ipv6_available)
        families = [socket.AF_INET]
        if test_ipv6:
            families.append(socket.AF_INET6)

        dns_ip = self._detect_dns_fn() if enable_dns else ""

        # Prepare HTTPS canary targets per family (cached-IP host canary or direct-IP cold-start fallback)
        canary_tasks: list[tuple[int, str, str, str, tuple[int, ...], bool]] = []
        for family in families:
            host_targets: list[tuple[str, CanarySpec]] = []
            for spec in self._host_canaries:
                ip = self._resolve_cached_ip(spec.host, family, now_mono)
                if ip:
                    host_targets.append((ip, spec))

            if host_targets:
                for ip, spec in host_targets:
                    canary_tasks.append((family, spec.host, ip, spec.path, spec.expected_statuses, False))
            else:
                # Cold start during DNS outage: fall back to direct-IP HTTPS canaries
                for d_spec in self._direct_ip_canaries:
                    d_ip = d_spec.ipv6 if family == socket.AF_INET6 else d_spec.ipv4
                    if d_ip:
                        canary_tasks.append((family, d_ip, d_ip, d_spec.path, d_spec.expected_statuses, True))

        if self._stop_event.is_set():
            return self.get_snapshot()

        lan_ping_res: float | None = None
        dns_res: DnsQueryResult | None = None
        canary_results: list[tuple[int, str, bool, HttpsCanaryResult]] = []

        with ThreadPoolExecutor(max_workers=6) as pool:
            lan_future = pool.submit(self._ping_fn, gateway_ip) if gateway_ip else None
            dns_future = (
                pool.submit(self._dns_fn, dns_ip)
                if (enable_dns and enable_uncached and dns_ip)
                else None
            )
            c_futures = [
                (
                    family,
                    sni_host,
                    is_direct,
                    pool.submit(
                        self._canary_fn,
                        connect_ip,
                        sni_host,
                        path=path,
                        family=family,
                        expected_statuses=expected_statuses,
                    ),
                )
                for family, sni_host, connect_ip, path, expected_statuses, is_direct in canary_tasks
            ]

            if lan_future is not None:
                try:
                    lan_ping_res = lan_future.result()
                except Exception:
                    lan_ping_res = None

            if dns_future is not None:
                try:
                    dns_res = dns_future.result()
                except Exception:
                    dns_res = DnsQueryResult(ok=False, error="socket_error")

            for family, sni_host, is_direct, fut in c_futures:
                try:
                    res = fut.result()
                except Exception:
                    res = HttpsCanaryResult(ok=False, error="connect_error")
                canary_results.append((family, sni_host, is_direct, res))

        if self._stop_event.is_set():
            return self.get_snapshot()

        v4_rtts: list[float] = []
        v4_total = 0
        v6_rtts: list[float] = []
        v6_total = 0
        captive_portal = False

        for family, _sni, _is_direct, res in canary_results:
            if res.error == "captive_portal":
                captive_portal = True
            if family == socket.AF_INET:
                v4_total += 1
                if res.ok and res.latency_ms is not None:
                    v4_rtts.append(res.latency_ms)
            elif family == socket.AF_INET6:
                v6_total += 1
                if res.ok and res.latency_ms is not None:
                    v6_rtts.append(res.latency_ms)

        # Invalidate cached IPs for failed host canaries if DNS appears healthy (handles CDN IP rotation)
        if dns_res is None or dns_res.ok:
            with self._lock:
                for family, sni_host, is_direct, res in canary_results:
                    if not is_direct and not res.ok:
                        self._ip_cache.pop((sni_host, family), None)

        with self._lock:
            self._probe_count += 1
            self._last_probe_ts = time.monotonic()
            self._last_probe_wall = time.time()

            self._gateway_ip = gateway_ip
            self._lan_ping_ms = lan_ping_res
            if gateway_ip:
                self._lan_window.record(lan_ping_res)
                # If router blocks ICMP/TCP probes completely while UPnP responds cleanly, do not report false LAN failure
                if (
                    box_reachable
                    and not is_local_fallback
                    and lan_ping_res is None
                    and not self._lan_window.has_any_success()
                ):
                    self._lan_ok = True
                else:
                    _, _, lan_loss, _, _, _, lan_consec = self._lan_window.stats()
                    self._lan_ok = lan_consec < 2 and lan_loss <= HealthEvaluator.LAN_LOSS_ERR_PCT
            else:
                self._lan_ok = not (not box_reachable and not is_local_fallback)

            self._ipv4_ok_count = len(v4_rtts)
            self._ipv4_total = v4_total
            self._ipv4_ms = round(min(v4_rtts), 2) if v4_rtts else None

            self._ipv6_available = ipv6_available
            self._ipv6_ok_count = len(v6_rtts)
            self._ipv6_total = v6_total
            self._ipv6_ms = round(min(v6_rtts), 2) if v6_rtts else None

            self._captive_portal = captive_portal

            self._dns_ip = dns_ip
            if not enable_dns or not enable_uncached:
                self._dns_ok = None
                self._dns_ms = None
                self._dns_rcode = None
                self._dns_error = ""
            elif not dns_ip:
                self._dns_ok = False
                self._dns_ms = None
                self._dns_rcode = None
                self._dns_error = "no_dns_server"
            elif dns_res is not None:
                self._dns_ok = dns_res.ok
                self._dns_ms = dns_res.latency_ms
                self._dns_rcode = dns_res.rcode
                self._dns_error = dns_res.error

            snapshot = self._build_snapshot_locked(advance_hysteresis=True)
            self._last_snapshot = snapshot
            return snapshot

    def _build_snapshot_locked(self, *, advance_hysteresis: bool) -> InternetHealthSnapshot:
        """Assemble snapshot from current state; caller must hold self._lock."""
        wan_total, wan_losses, wan_loss_pct, wan_med, wan_p95, wan_jit, _ = self._wan_window.stats()
        if self._gateway_ip and self._lan_window.has_any_success():
            _, _, lan_loss_pct, _, _, _, lan_consec = self._lan_window.stats()
        else:
            lan_loss_pct = 0.0
            lan_consec = 0 if self._lan_ok else 2

        return self._evaluator.evaluate(
            probe_count=self._probe_count,
            box_reachable=self._box_reachable,
            physical_link_up=self._physical_link_up,
            wan_connected=self._wan_connected,
            is_local_fallback=self._is_local_fallback,
            gateway_ip=self._gateway_ip,
            lan_ping_ms=self._lan_ping_ms,
            lan_loss_pct=lan_loss_pct,
            lan_consecutive_fails=lan_consec,
            lan_ok=self._lan_ok,
            ipv4_ok_count=self._ipv4_ok_count,
            ipv4_total=self._ipv4_total,
            ipv4_ms=self._ipv4_ms,
            ipv6_available=self._ipv6_available,
            ipv6_ok_count=self._ipv6_ok_count,
            ipv6_total=self._ipv6_total,
            ipv6_ms=self._ipv6_ms,
            ip_mode=self.ip_mode,
            captive_portal_detected=self._captive_portal,
            dns_enabled=(self.enable_dns_monitor and self.enable_uncached_dns),
            dns_ip=self._dns_ip,
            dns_ok=self._dns_ok,
            dns_ms=self._dns_ms,
            dns_rcode=self._dns_rcode,
            dns_error=self._dns_error,
            wan_samples=wan_total,
            wan_loss_count=wan_losses,
            wan_loss_pct=wan_loss_pct,
            wan_median_ms=wan_med,
            wan_p95_ms=wan_p95,
            wan_jitter_ms=wan_jit,
            baseline_rtt_ms=self._baseline.baseline_rtt_ms,
            baseline_jitter_ms=self._baseline.baseline_jitter_ms,
            baseline_ready=self._baseline.is_ready,
            p95_thresh=self._baseline.p95_warn_threshold(),
            jitter_thresh=self._baseline.jitter_warn_threshold(),
            is_line_saturated=(self._line_utilization >= self.LINE_SATURATION_THRESHOLD),
            last_probe_ts=self._last_probe_wall,
            advance_hysteresis=advance_hysteresis,
        )
