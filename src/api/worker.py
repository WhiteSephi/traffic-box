"""Background worker orchestrating network polling for UPnP, Fritz!OS, ping, and local traffic."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Signal, Slot

from src.api.fritz_monitor import FritzGuestMonitorClient
from src.api.local_traffic import LocalTrafficMonitor
from src.api.models import OnlineCounterStats, TrafficSample
from src.api.net_health import NetworkHealthMonitor, set_shutting_down
from src.api.upnp_client import FritzUpnpClient
from src.config import AppConfig


class PollingWorker(QObject):
    """Background worker that polls Fritz!Box UPnP & optional Guest Monitor off the GUI thread."""

    sample_ready = Signal(object)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.upnp = FritzUpnpClient(
            host=self.config.fritzbox_host,
            port=self.config.upnp_port,
        )
        self.guest_client = FritzGuestMonitorClient(
            host=self.upnp.host,
            username=self.config.fritz_username,
            password=self.config.fritz_password,
        )
        self.net_health = NetworkHealthMonitor(endpoint=self.config.ping_endpoint)
        self.local_traffic = LocalTrafficMonitor()
        self._cached_counters = OnlineCounterStats()
        self._counter_tick: int = 0
        self._last_upnp_probe_ts: float = 0.0
        self._box_unreachable: bool = False
        self._busy = False
        self._stopped = False

    UPNP_RETRY_COOLDOWN_SEC: float = 10.0

    def stop(self) -> None:
        """Immediately mark worker as stopped to abort pending/future polls during OS shutdown."""
        self._stopped = True
        set_shutting_down(True)
        try:
            self.guest_client.logout(timeout=0.4)
        except Exception:
            pass

    @Slot()
    def poll_once(self) -> None:
        """Execute a single network poll and emit the resulting TrafficSample."""
        if self._busy or self._stopped:
            return
        self._busy = True
        try:
            now = time.monotonic()
            if (
                self._box_unreachable
                and (now - self._last_upnp_probe_ts) < self.UPNP_RETRY_COOLDOWN_SEC
            ):
                sample = TrafficSample(
                    box_reachable=False,
                    physical_link_up=False,
                    wan_connected=False,
                    is_connected=False,
                    connection_status="Nicht erreichbar",
                )
            else:
                self.upnp.update_target(self.config.fritzbox_host, self.config.upnp_port)
                self.guest_client.update_credentials(
                    self.upnp.host, self.config.fritz_username, self.config.fritz_password
                )
                self._last_upnp_probe_ts = now
                sample = self.upnp.fetch_sample()
                self._box_unreachable = not sample.box_reachable
            if self._stopped:
                return

            # Guard against foreign Fritz!Box login attempts (roaming / multi-box protection, fail-closed)
            is_foreign = False
            if sample.box_reachable:
                if self.config.bound_box_udn:
                    if not sample.box_udn or sample.box_udn.lower() != self.config.bound_box_udn.lower():
                        is_foreign = True
                elif sample.box_udn and self.config.fritz_password:
                    # Auto-bind initial box if credentials exist but bound_box_udn was not yet stored
                    self.config.bound_box_udn = sample.box_udn
                    self.config.bound_box_name = sample.box_name
                    self.config.save()

            sample.is_foreign_box = is_foreign
            has_verified_box = (not self.config.bound_box_udn) or bool(sample.box_udn)

            if (
                sample.box_reachable
                and sample.is_connected
                and self.config.enable_guest_monitor
                and self.config.fritz_password
                and not is_foreign
                and has_verified_box
                and not self._stopped
            ):
                self.guest_client.update_credentials(
                    self.upnp.host,
                    self.config.fritz_username,
                    self.config.fritz_password,
                )
                g_down, g_up, g_ok = self.guest_client.fetch_guest_rates_bps()
                if g_ok:
                    sample.guest_download_bps = min(sample.download_bps, g_down)
                    sample.guest_upload_bps = min(sample.upload_bps, g_up)
                    sample.guest_active = True

                if (
                    self._counter_tick % 15 == 0 or not self._cached_counters.is_available
                ) and not self._stopped:
                    fresh_counters = self.guest_client.fetch_online_counters()
                    if fresh_counters.is_available:
                        self._cached_counters = fresh_counters
                    else:
                        self._cached_counters = OnlineCounterStats()
                self._counter_tick += 1
                sample.online_counters = self._cached_counters
            else:
                self._counter_tick = 0
                self._cached_counters = OnlineCounterStats()

            if self._stopped:
                return

            # Execute network health diagnostics off the GUI thread
            self.net_health.set_endpoint(self.config.ping_endpoint)
            ping_val, jitter_val, dns_ip, dns_ms = self.net_health.tick(
                check_ping=self.config.enable_ping_graph,
                check_dns=self.config.enable_dns_monitor,
            )
            sample.ping_ms = ping_val
            sample.jitter_ms = jitter_val
            sample.active_dns_ip = dns_ip
            sample.dns_ms = dns_ms

            if self._stopped:
                return

            # Fallback to local network adapter traffic when no Fritz!Box is reachable
            if (
                not sample.box_reachable
                and self.config.enable_local_fallback
                and not self._stopped
            ):
                pc_down, pc_up, pc_ok = self.local_traffic.fetch_rates_bps()
                if pc_ok:
                    sample.is_local_fallback = True
                    sample.is_connected = True
                    sample.download_bps = pc_down
                    sample.upload_bps = pc_up
                    sample.session_bytes_received = self.local_traffic.session_bytes_received
                    sample.session_bytes_sent = self.local_traffic.session_bytes_sent
                    sample.connection_status = "Lokal (Fallback)"
            # Measure local device (PC) traffic overlay if Fritz!Box is connected and option is enabled
            elif (
                sample.box_reachable
                and sample.is_connected
                and self.config.enable_local_traffic_monitor
            ):
                pc_down, pc_up, pc_ok = self.local_traffic.fetch_rates_bps()
                if pc_ok:
                    sample.local_pc_active = True
                    # Detect LAN/NAS spikes (where local traffic significantly exceeds Fritz!Box WAN throughput)
                    is_down_lan = pc_down > (sample.download_bps * 1.5) and pc_down > (5 * 1024 * 1024)
                    is_up_lan = pc_up > (sample.upload_bps * 1.5) and pc_up > (5 * 1024 * 1024)
                    sample.local_pc_is_lan_spike = is_down_lan or is_up_lan

                    # Clamp internet share so it never exceeds WAN bandwidth in the graph
                    sample.local_pc_download_bps = min(sample.download_bps, pc_down)
                    sample.local_pc_upload_bps = min(sample.upload_bps, pc_up)

            if not self._stopped:
                self.sample_ready.emit(sample)
        finally:
            self._busy = False

    @Slot()
    def reset_session(self) -> None:
        """Reset cumulative session counters."""
        self.upnp.reset_session_counters()
        self.local_traffic.reset_session_counters()

    @Slot()
    def reload_credentials(self) -> None:
        """Reset cached session and counters when user updates settings."""
        self._cached_counters = OnlineCounterStats()
        self._counter_tick = 0
        self._last_upnp_probe_ts = 0.0
        self._box_unreachable = False
        self.upnp.update_target(self.config.fritzbox_host, self.config.upnp_port)
        self.guest_client.update_credentials(
            self.upnp.host,
            self.config.fritz_username,
            self.config.fritz_password,
        )
