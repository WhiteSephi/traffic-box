"""Data models for Fritz!Box traffic measurements."""

from __future__ import annotations

from dataclasses import dataclass


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
    connection_status: str = "Unbekannt"
    uptime_seconds: int = 0
    external_ip: str = "-"
    is_connected: bool = False
    guest_active: bool = False
    error_message: str = ""
