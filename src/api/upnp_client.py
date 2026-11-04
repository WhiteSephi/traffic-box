"""Passwordless UPnP SOAP client for AVM Fritz!Box (Port 49000)."""

from __future__ import annotations

import socket
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from src.api.models import TrafficSample

WAN_COMMON_SERVICE = "urn:schemas-upnp-org:service:WANCommonInterfaceConfig:1"
WAN_IP_SERVICE = "urn:schemas-upnp-org:service:WANIPConnection:1"
WAN_PPP_SERVICE = "urn:schemas-upnp-org:service:WANPPPConnection:1"


def detect_default_gateway() -> str:
    """Detect the default gateway/router IPv4 address on Linux and Windows."""
    if sys.platform != "win32":
        try:
            with open("/proc/net/route", "r", encoding="utf-8") as f:
                for line in f:
                    fields = line.strip().split()
                    if len(fields) >= 3 and fields[1] == "00000000":
                        gw_hex = fields[2]
                        octets = [str(int(gw_hex[i : i + 2], 16)) for i in (6, 4, 2, 0)]
                        gw_ip = ".".join(octets)
                        if gw_ip != "0.0.0.0":
                            return gw_ip
        except Exception:
            pass

    # Generic routing UDP socket fallback (works without sending network packets)
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        local_ip = s.getsockname()[0]
        parts = local_ip.split(".")
        if len(parts) == 4 and parts[0] in ("192", "10", "172"):
            return f"{parts[0]}.{parts[1]}.{parts[2]}.1"
    except Exception:
        pass
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass

    return ""


def resolve_fritzbox_host(host: str) -> str:
    """Resolve Fritz!Box host, falling back to default gateway if fritz.box points to a public IP or fails."""
    clean = host.strip() or "fritz.box"
    if clean.lower() != "fritz.box":
        return clean

    # Check if fritz.box resolves to a private RFC 1918 IP
    try:
        resolved = socket.gethostbyname("fritz.box")
        parts = resolved.split(".")
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            p0, p1 = int(parts[0]), int(parts[1])
            if p0 == 10 or (p0 == 172 and 16 <= p1 <= 31) or (p0 == 192 and p1 == 168):
                return resolved
    except Exception:
        pass

    # If fritz.box resolved to a public IP (e.g. DNS parking/catchall) or failed, use detected gateway
    gw = detect_default_gateway()
    if gw:
        return gw

    return "fritz.box"


class FritzUpnpClient:
    """Queries live WAN throughput and line capacity via Fritz!Box UPnP SOAP."""

    def __init__(self, host: str = "fritz.box", port: int = 49000, timeout: float = 1.8) -> None:
        self.configured_host = host.strip() or "fritz.box"
        self.host = resolve_fritzbox_host(self.configured_host)
        self.port = port
        self.timeout = timeout

        self._common_control_url: str | None = None
        self._wan_conn_control_url: str | None = None
        self._wan_conn_service: str = WAN_IP_SERVICE
        self._box_friendly_name: str = ""
        self._box_udn: str = ""

        # Cached link & connection info (polled less frequently than 1s traffic)
        self._max_down_bps: float = 0.0
        self._max_up_bps: float = 0.0
        self._physical_status: str = "Up"
        self._conn_status: str = "Connected"
        self._uptime_sec: int = 0
        self._external_ip: str = "-"
        self._tick_counter: int = 0

        # Session byte counter tracking (handles 32-bit wrap-around)
        self._last_raw_rx: int | None = None
        self._last_raw_tx: int | None = None
        self._session_rx: int = 0
        self._session_tx: int = 0

    def update_target(self, host: str, port: int = 49000) -> None:
        """Update target Fritz!Box host/IP and reset discovered URLs if changed."""
        clean_host = host.strip() or "fritz.box"
        resolved = resolve_fritzbox_host(clean_host)
        if clean_host != self.configured_host or resolved != self.host or port != self.port:
            self.configured_host = clean_host
            self.host = resolved
            self.port = port
            self._common_control_url = None
            self._wan_conn_control_url = None
            self._box_friendly_name = ""
            self._box_udn = ""
            self._tick_counter = 0

    def _discover_endpoints(self) -> None:
        """Discover UPnP control URLs from /igddesc.xml with sensible AVM defaults."""
        self._common_control_url = "/igdupnp/control/WANCommonIFC1"
        self._wan_conn_control_url = "/igdupnp/control/WANIPConn1"
        self._wan_conn_service = WAN_IP_SERVICE

        url = f"http://{self.host}:{self.port}/igddesc.xml"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                xml_bytes = resp.read()
            root = ET.fromstring(xml_bytes)
            for elem in root.iter():
                tag = elem.tag.split("}", 1)[-1]
                if tag == "friendlyName" and elem.text and not self._box_friendly_name:
                    self._box_friendly_name = elem.text.strip()
                elif tag == "UDN" and elem.text and not self._box_udn:
                    self._box_udn = elem.text.strip()

            for service in root.iter():
                if not service.tag.endswith("service"):
                    continue
                svc_type = ""
                ctrl_url = ""
                for child in service:
                    if child.tag.endswith("serviceType") and child.text:
                        svc_type = child.text.strip()
                    elif child.tag.endswith("controlURL") and child.text:
                        ctrl_url = child.text.strip()
                if not ctrl_url:
                    continue
                if not ctrl_url.startswith("/"):
                    ctrl_url = "/" + ctrl_url
                if "WANCommonInterfaceConfig:1" in svc_type:
                    self._common_control_url = ctrl_url
                elif "WANIPConnection:1" in svc_type:
                    self._wan_conn_control_url = ctrl_url
                    self._wan_conn_service = WAN_IP_SERVICE
                elif "WANPPPConnection:1" in svc_type and self._wan_conn_control_url is None:
                    self._wan_conn_control_url = ctrl_url
                    self._wan_conn_service = WAN_PPP_SERVICE
        except (urllib.error.URLError, ET.ParseError, TimeoutError, OSError):
            # Fallback paths will be tried directly during SOAP call
            pass

    @property
    def box_name(self) -> str:
        """Return discovered friendly device name (e.g. 'FRITZ!Box 7590')."""
        return self._box_friendly_name

    @property
    def box_udn(self) -> str:
        """Return unique device UDN / UUID (e.g. 'uuid:12345678-0000-0000-0000-001122334455')."""
        return self._box_udn

    def _soap_call(self, control_path: str, service_urn: str, action: str) -> dict[str, str]:
        """Execute a UPnP SOAP action and parse the resulting XML tags into a dict."""
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f'<s:Body><u:{action} xmlns:u="{service_urn}"></u:{action}></s:Body>'
            "</s:Envelope>"
        ).encode("utf-8")

        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"{service_urn}#{action}"',
        }
        url = f"http://{self.host}:{self.port}{control_path}"
        req = urllib.request.Request(url, data=envelope, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw_xml = resp.read()

        root = ET.fromstring(raw_xml)
        result: dict[str, str] = {}
        for elem in root.iter():
            tag_name = elem.tag.split("}", 1)[-1]
            if tag_name.startswith("New") and elem.text is not None:
                result[tag_name] = elem.text.strip()
        return result

    def _call_common_ifc(self, action: str) -> dict[str, str]:
        """Call an action on WANCommonInterfaceConfig:1 with automatic path fallback."""
        if not self._common_control_url:
            self._discover_endpoints()

        candidate_paths = [
            self._common_control_url or "/igdupnp/control/WANCommonIFC1",
            "/upnp/control/WANCommonIFC1",
            "/igdupnp/control/WANCommonIFC1",
        ]
        # Deduplicate while preserving order
        seen: set[str] = set()
        paths = [p for p in candidate_paths if not (p in seen or seen.add(p))]

        last_exc: Exception | None = None
        for path in paths:
            try:
                res = self._soap_call(path, WAN_COMMON_SERVICE, action)
                self._common_control_url = path
                return res
            except (urllib.error.URLError, ET.ParseError, TimeoutError, OSError) as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        return {}

    def _update_session_counters(self, rx_total: int, tx_total: int, is_64bit: bool) -> None:
        """Update cumulative session byte counters with 32-bit overflow protection."""
        if self._last_raw_rx is not None:
            delta_rx = rx_total - self._last_raw_rx
            if delta_rx < 0 and not is_64bit:
                delta_rx += 1 << 32
            if delta_rx > 0:
                self._session_rx += delta_rx

        if self._last_raw_tx is not None:
            delta_tx = tx_total - self._last_raw_tx
            if delta_tx < 0 and not is_64bit:
                delta_tx += 1 << 32
            if delta_tx > 0:
                self._session_tx += delta_tx

        self._last_raw_rx = rx_total
        self._last_raw_tx = tx_total

    def reset_session_counters(self) -> None:
        """Reset session traffic counters to zero."""
        self._session_rx = 0
        self._session_tx = 0

    def fetch_sample(self) -> TrafficSample:
        """Poll current throughput and periodic link/status info from Fritz!Box."""
        sample = TrafficSample()
        try:
            addon = self._call_common_ifc("GetAddonInfos")
            sample.download_bps = float(addon.get("NewByteReceiveRate", "0") or 0)
            sample.upload_bps = float(addon.get("NewByteSendRate", "0") or 0)

            has_64 = "NewX_AVM_DE_TotalBytesReceived64" in addon
            rx_total = int(
                addon.get("NewX_AVM_DE_TotalBytesReceived64")
                or addon.get("NewTotalBytesReceived")
                or 0
            )
            tx_total = int(
                addon.get("NewX_AVM_DE_TotalBytesSent64")
                or addon.get("NewTotalBytesSent")
                or 0
            )
            self._update_session_counters(rx_total, tx_total, has_64)

            sample.total_bytes_received = rx_total
            sample.total_bytes_sent = tx_total
            sample.session_bytes_received = self._session_rx
            sample.session_bytes_sent = self._session_tx

            # Refresh link properties and WAN connection info every 15 ticks (or first tick)
            if self._tick_counter % 15 == 0:
                try:
                    link = self._call_common_ifc("GetCommonLinkProperties")
                    down_max_bits = float(link.get("NewLayer1DownstreamMaxBitRate", "0") or 0)
                    up_max_bits = float(link.get("NewLayer1UpstreamMaxBitRate", "0") or 0)
                    self._physical_status = link.get("NewPhysicalLinkStatus", "Up")
                    if self._physical_status.lower() == "up":
                        if down_max_bits > 0:
                            self._max_down_bps = down_max_bits / 8.0
                        if up_max_bits > 0:
                            self._max_up_bps = up_max_bits / 8.0
                    else:
                        self._max_down_bps = 0.0
                        self._max_up_bps = 0.0
                except (urllib.error.URLError, ET.ParseError, TimeoutError, OSError):
                    pass

                if self._wan_conn_control_url:
                    try:
                        status_info = self._soap_call(
                            self._wan_conn_control_url, self._wan_conn_service, "GetStatusInfo"
                        )
                        self._conn_status = status_info.get("NewConnectionStatus", "Connected")
                        self._uptime_sec = int(status_info.get("NewUptime", "0") or 0)
                    except (urllib.error.URLError, ET.ParseError, TimeoutError, OSError):
                        pass
                    try:
                        ip_info = self._soap_call(
                            self._wan_conn_control_url,
                            self._wan_conn_service,
                            "GetExternalIPAddress",
                        )
                        ext_ip = ip_info.get("NewExternalIPAddress", "")
                        if ext_ip:
                            self._external_ip = ext_ip
                    except (urllib.error.URLError, ET.ParseError, TimeoutError, OSError):
                        pass

            self._tick_counter += 1
            sample.box_name = self._box_friendly_name
            sample.box_udn = self._box_udn
            sample.box_reachable = True
            sample.physical_link_up = self._physical_status.lower() == "up"
            sample.wan_connected = sample.physical_link_up and (self._conn_status.lower() == "connected")
            sample.is_connected = sample.wan_connected
            sample.max_download_bps = self._max_down_bps
            sample.max_upload_bps = self._max_up_bps
            sample.connection_status = self._conn_status
            sample.uptime_seconds = self._uptime_sec
            sample.external_ip = self._external_ip
            return sample

        except Exception as exc:
            sample.box_name = self._box_friendly_name
            sample.box_udn = self._box_udn
            sample.box_reachable = False
            sample.physical_link_up = False
            sample.wan_connected = False
            sample.is_connected = False
            sample.connection_status = "Nicht erreichbar"
            sample.error_message = str(exc)
            return sample
