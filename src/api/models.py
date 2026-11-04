"""Data models for Fritz!Box traffic measurements and online counters."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    error_message: str = ""
