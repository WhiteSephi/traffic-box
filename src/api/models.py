"""Data models for Fritz!Box traffic measurements and online counters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class HealthStatus(str, Enum):
    """Five-level connectivity & quality classification (plus initial UNKNOWN state)."""

    UNKNOWN = "unknown"
    STABLE = "stable"
    DEGRADED = "degraded"
    DNS_ERROR = "dns_error"
    OFFLINE = "offline"
    ZOMBIE_WAN = "zombie_wan"
    LAN_ERROR = "lan_error"


@dataclass(frozen=True)
class InternetHealthSnapshot:
    """Thread-safe point-in-time summary of multi-stage internet health diagnostics."""

    status: HealthStatus = HealthStatus.UNKNOWN
    reason: str = ""
    short_tag: str = ""
    gateway_ip: str = ""
    lan_ping_ms: float | None = None
    lan_loss_pct: float = 0.0
    lan_ok: bool = True
    ipv4_ok: bool | None = None
    ipv4_quorum: tuple[int, int] = (0, 0)
    ipv4_ms: float | None = None
    ipv6_available: bool = False
    ipv6_ok: bool | None = None
    ipv6_quorum: tuple[int, int] = (0, 0)
    ipv6_ms: float | None = None
    captive_portal_detected: bool = False
    dns_ip: str = ""
    dns_ok: bool | None = None
    dns_ms: float | None = None
    dns_rcode: int | None = None
    dns_error: str = ""
    wan_loss_pct: float = 0.0
    wan_median_ms: float | None = None
    wan_p95_ms: float | None = None
    wan_jitter_ms: float = 0.0
    baseline_rtt_ms: float | None = None
    baseline_jitter_ms: float | None = None
    baseline_ready: bool = False
    is_line_saturated: bool = False
    in_burst_mode: bool = False
    probe_count: int = 0
    last_probe_ts: float = 0.0


@dataclass
class PeriodCounter:
    """Sent and received byte volume for a specific time period (e.g., Today, ThisMonth)."""

    received_bytes: int = 0
    sent_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        """Return combined sent + received bytes."""
        return self.received_bytes + self.sent_bytes


@dataclass
class OnlineCounterStats:
    """Fritz!Box Online-Zähler statistics across all tracked periods."""

    today: PeriodCounter = field(default_factory=PeriodCounter)
    yesterday: PeriodCounter = field(default_factory=PeriodCounter)
    this_week: PeriodCounter = field(default_factory=PeriodCounter)
    this_month: PeriodCounter = field(default_factory=PeriodCounter)
    last_month: PeriodCounter = field(default_factory=PeriodCounter)
    is_available: bool = False


@dataclass
class TrafficSample:
    """Single point-in-time traffic and status measurement from the Fritz!Box."""

    download_bps: float = 0.0  # Bytes per second (total WAN downstream)
    upload_bps: float = 0.0  # Bytes per second (total WAN upstream)
    guest_download_bps: float = 0.0  # Bytes per second (guest network downstream share)
    guest_upload_bps: float = 0.0  # Bytes per second (guest network upstream share)
    max_download_bps: float = 0.0  # Max line capacity in bytes per second
    max_upload_bps: float = 0.0  # Max line capacity in bytes per second
    total_bytes_received: int = 0
    total_bytes_sent: int = 0
    session_bytes_received: int = 0
    session_bytes_sent: int = 0
    online_counters: OnlineCounterStats = field(default_factory=OnlineCounterStats)
    connection_status: str = "Unbekannt"
    uptime_seconds: int = 0
    external_ip: str = "-"
    is_connected: bool = False
    box_reachable: bool = True
    physical_link_up: bool = True
    wan_connected: bool = True
    ping_ms: float | None = None
    jitter_ms: float = 0.0
    active_dns_ip: str = ""
    dns_ms: float | None = None
    guest_active: bool = False
    local_pc_download_bps: float = 0.0  # Bytes per second (local machine internet share)
    local_pc_upload_bps: float = 0.0  # Bytes per second (local machine internet share)
    local_pc_active: bool = False
    local_pc_is_lan_spike: bool = False
    is_local_fallback: bool = False
    box_name: str = ""
    box_udn: str = ""
    is_foreign_box: bool = False
    error_message: str = ""
    ping_lost: bool = False
    health: InternetHealthSnapshot = field(default_factory=InternetHealthSnapshot)
