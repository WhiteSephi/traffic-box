"""Offline unit tests for multi-stage internet health diagnostics (api/internet_health.py)."""

from __future__ import annotations

import socket
import unittest
from unittest.mock import MagicMock

from src.api.internet_health import (
    BaselineTracker,
    HealthStatus,
    InternetHealthMonitor,
    SlidingWindowTracker,
)
from src.api.models import TrafficSample
from src.api.net_health import DnsQueryResult, HttpsCanaryResult, set_shutting_down
from src.api.worker import PollingWorker
from src.config import AppConfig


def _ok_canary(connect_ip: str, server_hostname: str, **kwargs) -> HttpsCanaryResult:
    return HttpsCanaryResult(ok=True, latency_ms=22.0, status_code=204)


def _fail_canary(connect_ip: str, server_hostname: str, **kwargs) -> HttpsCanaryResult:
    return HttpsCanaryResult(ok=False, error="timeout")


def _captive_canary(connect_ip: str, server_hostname: str, **kwargs) -> HttpsCanaryResult:
    return HttpsCanaryResult(ok=False, latency_ms=15.0, status_code=302, error="captive_portal")


def _ok_dns(dns_server: str) -> DnsQueryResult:
    return DnsQueryResult(ok=True, latency_ms=24.0, rcode=3)


def _ok_resolve(host: str, family: int) -> str:
    if family == socket.AF_INET6:
        return "2606:4700::6810:1" if "cloudflare" in host else "2001:4860:4860::1"
    return "198.51.100.1" if "cloudflare" in host else "198.51.100.2"


class TestSlidingWindowAndBaseline(unittest.TestCase):
    """Test sliding window percentiles, loss calculation, and idle baseline learning."""

    def test_sliding_window_stats(self) -> None:
        win = SlidingWindowTracker(window_size=20)
        # 18 successful pings + 2 losses = 10% loss
        for val in [10.0, 12.0, 11.0, 13.0, 12.0, 14.0, 15.0, 11.0, 12.0, 13.0,
                    12.0, 11.0, 14.0, 13.0, 12.0, 15.0, 16.0, 40.0]:
            win.record(val)
        win.record(None)
        win.record(None)

        total, losses, loss_pct, med, p95, jitter, consec = win.stats()
        self.assertEqual(total, 20)
        self.assertEqual(losses, 2)
        self.assertEqual(loss_pct, 10.0)
        self.assertEqual(consec, 2)
        self.assertIsNotNone(med)
        self.assertAlmostEqual(med, 12.5, places=1)
        self.assertEqual(p95, 40.0)
        self.assertGreater(jitter, 0.0)

    def test_baseline_ignores_high_load_and_applies_floors(self) -> None:
        base = BaselineTracker(min_samples=10)
        # High utilization (>= 40%) must NOT update baseline
        for _ in range(15):
            base.update(85.0, 25.0, is_healthy=True, line_utilization=0.65)
        self.assertFalse(base.is_ready)
        self.assertIsNone(base.baseline_rtt_ms)

        # Clean idle samples learn low latency & tiny jitter
        for _ in range(12):
            base.update(8.0, 0.4, is_healthy=True, line_utilization=0.05)
        self.assertTrue(base.is_ready)
        self.assertAlmostEqual(base.baseline_rtt_ms or 0.0, 8.0, delta=0.5)

        # Floors prevent false positives on super-clean lines
        self.assertGreaterEqual(base.p95_warn_threshold() or 0.0, 50.0)
        self.assertGreaterEqual(base.jitter_warn_threshold() or 0.0, 15.0)


class TestInternetHealthStates(unittest.TestCase):
    """Test all five health states, quorum, hysteresis, IPv6 auto-detect, and IP cache fallback."""

    def _make_monitor(self, **overrides) -> InternetHealthMonitor:
        defaults = dict(
            probe_interval_sec=30,
            burst_interval_sec=5,
            ip_mode="auto",
            enable_uncached_dns=True,
            enable_dns_monitor=True,
            ping_fn=lambda host: 0.8,
            dns_fn=_ok_dns,
            detect_dns_fn=lambda: "192.168.178.2",
            canary_fn=_ok_canary,
            ipv6_fn=lambda: True,
            resolve_fn=_ok_resolve,
            gateway_fn=lambda: "192.168.178.1",
        )
        defaults.update(overrides)
        mon = InternetHealthMonitor(**defaults)
        mon._router_host = "192.168.178.1"
        return mon

    def test_stable_dual_stack(self) -> None:
        mon = self._make_monitor()
        snap = mon.run_probe_cycle()
        self.assertEqual(snap.status, HealthStatus.STABLE)
        self.assertEqual(snap.ipv4_quorum, (2, 2))
        self.assertEqual(snap.ipv6_quorum, (2, 2))
        self.assertTrue(snap.dns_ok)
        self.assertFalse(snap.in_burst_mode)

    def test_quorum_tolerates_single_provider_failure(self) -> None:
        def one_down(connect_ip: str, server_hostname: str, **kwargs) -> HttpsCanaryResult:
            if "cloudflare" in server_hostname:
                return HttpsCanaryResult(ok=False, error="timeout")
            return HttpsCanaryResult(ok=True, latency_ms=25.0, status_code=204)

        mon = self._make_monitor(canary_fn=one_down)
        snap = mon.run_probe_cycle()
        self.assertEqual(snap.status, HealthStatus.STABLE)
        self.assertEqual(snap.ipv4_quorum, (1, 2))
        self.assertEqual(snap.ipv6_quorum, (1, 2))

    def test_zombie_wan_detected_with_hysteresis(self) -> None:
        state = {"down": False}

        def dynamic_canary(connect_ip: str, server_hostname: str, **kwargs) -> HttpsCanaryResult:
            return _fail_canary(connect_ip, server_hostname) if state["down"] else _ok_canary(connect_ip, server_hostname)

        mon = self._make_monitor(canary_fn=dynamic_canary)
        snap1 = mon.run_probe_cycle()
        self.assertEqual(snap1.status, HealthStatus.STABLE)

        # Internet dies while FRITZ!Box still reports wan_connected=True
        state["down"] = True
        snap2 = mon.run_probe_cycle()
        # Hysteresis: 1st failure does NOT flip yet, but activates 5s burst mode
        self.assertEqual(snap2.status, HealthStatus.STABLE)
        self.assertTrue(snap2.in_burst_mode)

        # 2nd consecutive failure confirms ZOMBIE_WAN
        snap3 = mon.run_probe_cycle()
        self.assertEqual(snap3.status, HealthStatus.ZOMBIE_WAN)
        self.assertEqual(snap3.short_tag, "Kein Internet")
        self.assertIn("FRITZ!Box-Sync", snap3.reason)

        # Recovery also uses hysteresis (requires 2 consecutive healthy cycles)
        state["down"] = False
        snap4 = mon.run_probe_cycle()
        self.assertEqual(snap4.status, HealthStatus.ZOMBIE_WAN)
        snap5 = mon.run_probe_cycle()
        self.assertEqual(snap5.status, HealthStatus.STABLE)
        self.assertFalse(snap5.in_burst_mode)

    def test_offline_in_local_fallback_and_captive_portal(self) -> None:
        mon = self._make_monitor(canary_fn=_captive_canary)
        mon._box_reachable = False
        mon._is_local_fallback = True
        mon._wan_connected = False
        snap = mon.run_probe_cycle()
        self.assertEqual(snap.status, HealthStatus.OFFLINE)
        self.assertTrue(snap.captive_portal_detected)
        self.assertIn("Captive Portal", snap.reason)

    def test_dns_error_when_https_ok_and_uncached_dns_fails(self) -> None:
        mon = self._make_monitor(
            dns_fn=lambda srv: DnsQueryResult(ok=False, latency_ms=12.0, rcode=2, error="servfail")
        )
        snap = mon.run_probe_cycle()
        self.assertEqual(snap.status, HealthStatus.DNS_ERROR)
        self.assertEqual(snap.short_tag, "DNS-Störung")
        self.assertIn("SERVFAIL", snap.reason)
        self.assertTrue(snap.ipv4_ok)
        self.assertFalse(snap.dns_ok)

    def test_dns_transition_100_to_200_remains_stable_above_200_degraded(self) -> None:
        mon_mid = self._make_monitor(
            dns_fn=lambda srv: DnsQueryResult(ok=True, latency_ms=150.0, rcode=3)
        )
        self.assertEqual(mon_mid.run_probe_cycle().status, HealthStatus.STABLE)

        mon_slow = self._make_monitor(
            dns_fn=lambda srv: DnsQueryResult(ok=True, latency_ms=240.0, rcode=3)
        )
        snap_slow = mon_slow.run_probe_cycle()
        self.assertEqual(snap_slow.status, HealthStatus.DEGRADED)
        self.assertEqual(snap_slow.short_tag, "DNS langsam")

    def test_ipv6_auto_detection_no_false_alarm_on_ipv4_only(self) -> None:
        mon = self._make_monitor(ipv6_fn=lambda: False)
        snap = mon.run_probe_cycle()
        self.assertEqual(snap.status, HealthStatus.STABLE)
        self.assertFalse(snap.ipv6_available)
        self.assertEqual(snap.ipv6_quorum, (0, 0))

    def test_dual_stack_partial_outage_ipv6_dead_or_ipv4_dead(self) -> None:
        def v6_dead(connect_ip: str, server_hostname: str, family: int = socket.AF_INET, **kwargs) -> HttpsCanaryResult:
            if family == socket.AF_INET6:
                return HttpsCanaryResult(ok=False, error="timeout")
            return HttpsCanaryResult(ok=True, latency_ms=20.0, status_code=204)

        mon1 = self._make_monitor(canary_fn=v6_dead, ipv6_fn=lambda: True)
        snap1 = mon1.run_probe_cycle()
        self.assertEqual(snap1.status, HealthStatus.DEGRADED)
        self.assertEqual(snap1.short_tag, "Nur IPv4")

        def v4_dead(connect_ip: str, server_hostname: str, family: int = socket.AF_INET, **kwargs) -> HttpsCanaryResult:
            if family == socket.AF_INET:
                return HttpsCanaryResult(ok=False, error="timeout")
            return HttpsCanaryResult(ok=True, latency_ms=19.0, status_code=204)

        mon2 = self._make_monitor(canary_fn=v4_dead, ipv6_fn=lambda: True)
        snap2 = mon2.run_probe_cycle()
        self.assertEqual(snap2.status, HealthStatus.DEGRADED)
        self.assertEqual(snap2.short_tag, "Nur IPv6")

    def test_lan_error_on_unreachable_gateway_or_lan_loss(self) -> None:
        mon = self._make_monitor(ping_fn=lambda host: None)
        mon._box_reachable = False
        mon._is_local_fallback = False
        snap = mon.run_probe_cycle()
        self.assertEqual(snap.status, HealthStatus.LAN_ERROR)
        self.assertIn("Heimnetz", snap.reason)

    def test_degraded_on_packet_loss_and_bufferbloat_hint(self) -> None:
        mon = self._make_monitor()
        mon.run_probe_cycle()

        for _ in range(16):
            mon._wan_window.record(12.0)
            mon._baseline.update(12.0, 1.0, is_healthy=True, line_utilization=0.1)
        self.assertTrue(mon._baseline.is_ready)

        mon._line_utilization = 0.90
        mon._wan_window.clear()
        for val in [12.0] * 17 + [95.0, 105.0, 110.0]:
            mon._wan_window.record(val)

        mon.run_probe_cycle()
        snap = mon.run_probe_cycle()
        self.assertEqual(snap.status, HealthStatus.DEGRADED)
        self.assertTrue(snap.is_line_saturated)
        self.assertIn("Leitung ausgelastet", snap.reason)

        mon._line_utilization = 0.05
        mon._wan_window.clear()
        for _ in range(17):
            mon._wan_window.record(12.0)
        for _ in range(3):
            mon._wan_window.record(None)
        mon.run_probe_cycle()
        snap_loss = mon.run_probe_cycle()
        self.assertEqual(snap_loss.status, HealthStatus.DEGRADED)
        self.assertIn("Paketverlust", snap_loss.reason)

    def test_ip_cache_survives_live_adguard_outage_and_cold_start_uses_direct_ip(self) -> None:
        dns_alive = {"ok": True}
        seen_targets: list[tuple[str, str]] = []

        def tracked_canary(connect_ip: str, server_hostname: str, **kwargs) -> HttpsCanaryResult:
            seen_targets.append((connect_ip, server_hostname))
            return HttpsCanaryResult(ok=True, latency_ms=21.0, status_code=204)

        def flaky_resolve(host: str, family: int) -> str:
            if not dns_alive["ok"]:
                return ""
            return _ok_resolve(host, family)

        # 1. Warm start caches host IPs, then DNS dies -> still uses cached IPs & reports DNS_ERROR
        mon = self._make_monitor(
            ipv6_fn=lambda: False,
            resolve_fn=flaky_resolve,
            canary_fn=tracked_canary,
            dns_fn=lambda srv: _ok_dns(srv) if dns_alive["ok"] else DnsQueryResult(ok=False, error="timeout"),
        )
        self.assertEqual(mon.run_probe_cycle().status, HealthStatus.STABLE)
        self.assertIn(("198.51.100.1", "cp.cloudflare.com"), seen_targets)

        dns_alive["ok"] = False
        seen_targets.clear()
        mon.run_probe_cycle()
        snap = mon.run_probe_cycle()
        self.assertEqual(snap.status, HealthStatus.DNS_ERROR)
        self.assertIn(("198.51.100.1", "cp.cloudflare.com"), seen_targets)

        # 2. Cold start while DNS is already dead -> falls back to direct-IP canaries (1.1.1.1 / 8.8.8.8)
        cold_targets: list[tuple[str, str]] = []

        def cold_canary(connect_ip: str, server_hostname: str, **kwargs) -> HttpsCanaryResult:
            cold_targets.append((connect_ip, server_hostname))
            return HttpsCanaryResult(ok=True, latency_ms=18.0, status_code=200)

        mon_cold = self._make_monitor(
            ipv6_fn=lambda: False,
            resolve_fn=lambda host, fam: "",
            canary_fn=cold_canary,
            dns_fn=lambda srv: DnsQueryResult(ok=False, error="timeout"),
        )
        snap_cold = mon_cold.run_probe_cycle()
        self.assertEqual(snap_cold.status, HealthStatus.DNS_ERROR)
        self.assertIn(("1.1.1.1", "1.1.1.1"), cold_targets)
        self.assertIn(("8.8.8.8", "8.8.8.8"), cold_targets)

    def test_worker_suppresses_1s_cached_dns_when_uncached_health_active(self) -> None:
        cfg = AppConfig(
            enable_ping_graph=True,
            enable_dns_monitor=True,
            enable_internet_health=True,
            health_uncached_dns=True,
        )
        worker = PollingWorker(cfg)
        worker.upnp.fetch_sample = MagicMock(
            return_value=TrafficSample(box_reachable=True, physical_link_up=True, wan_connected=True, is_connected=True)
        )
        worker.net_health.tick = MagicMock(return_value=(14.5, 1.2, "", None))
        mock_snap = self._make_monitor().run_probe_cycle()
        worker.internet_health.record_tick = MagicMock(return_value=mock_snap)

        samples: list[TrafficSample] = []
        worker.sample_ready.connect(samples.append)
        try:
            worker.poll_once()
        finally:
            worker.stop()
            set_shutting_down(False)

        worker.net_health.tick.assert_called_once_with(check_ping=True, check_dns=False)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].health.status, HealthStatus.STABLE)
        self.assertEqual(samples[0].active_dns_ip, "192.168.178.2")
        self.assertEqual(samples[0].dns_ms, 24.0)
        self.assertFalse(samples[0].ping_lost)

    def test_fast_recovery_after_download_spike(self) -> None:
        """After load spikes end, 13 clean pings must allow quick return to STABLE (~15-20s)."""
        mon = self._make_monitor()
        mon.run_probe_cycle()

        # 1. Learn clean idle baseline (~12 ms)
        for _ in range(15):
            mon._wan_window.record(12.0)
            mon._baseline.update(12.0, 0.8, is_healthy=True, line_utilization=0.05)
        self.assertTrue(mon._baseline.is_ready)

        # 2. Inject 10 download latency spikes (75 ms) -> 2 cycles -> DEGRADED
        mon._line_utilization = 0.85
        for _ in range(10):
            mon._wan_window.record(75.0)
        mon.run_probe_cycle()
        snap_deg = mon.run_probe_cycle()
        self.assertEqual(snap_deg.status, HealthStatus.DEGRADED)

        # 3. Line returns to idle with 13 clean pings (old spikes remain inside 60-sample window)
        mon._line_utilization = 0.05
        for _ in range(13):
            mon._wan_window.record(13.0)

        # Two burst cycles confirm recovery immediately instead of waiting 60-120s
        mon.run_probe_cycle()
        snap_rec = mon.run_probe_cycle()
        self.assertEqual(snap_rec.status, HealthStatus.STABLE)

    def test_stray_single_or_double_ping_spike_no_false_alarm(self) -> None:
        """One or two stray high pings inside the 15s window do not trigger DEGRADED."""
        mon = self._make_monitor()
        mon.run_probe_cycle()

        for _ in range(15):
            mon._wan_window.record(12.0)
            mon._baseline.update(12.0, 0.5, is_healthy=True, line_utilization=0.05)
        self.assertTrue(mon._baseline.is_ready)

        # Replace with 13 clean pings + 2 stray 80 ms spikes (p85 stays at 12 ms)
        mon._wan_window.clear()
        for _ in range(13):
            mon._wan_window.record(12.0)
        mon._wan_window.record(80.0)
        mon._wan_window.record(80.0)

        mon.run_probe_cycle()
        snap = mon.run_probe_cycle()
        self.assertEqual(snap.status, HealthStatus.STABLE)


if __name__ == "__main__":
    unittest.main()
