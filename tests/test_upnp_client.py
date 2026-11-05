"""Unit tests for api/upnp_client.py."""

from __future__ import annotations

import unittest

from src.api.upnp_client import FritzUpnpClient


class TestUpnpClient(unittest.TestCase):
    """Test UPnP client session tracking and 32-bit overflow handling."""

    def test_session_counter_tracking(self) -> None:
        """Verify normal increment of session byte counters."""
        client = FritzUpnpClient()
        self.assertEqual(client._session_rx, 0)
        self.assertEqual(client._session_tx, 0)

        # First tick: sets baseline
        client._update_session_counters(1_000_000, 500_000, is_64bit=True)
        self.assertEqual(client._session_rx, 0)
        self.assertEqual(client._session_tx, 0)

        # Second tick: delta +200_000 rx, +100_000 tx
        client._update_session_counters(1_200_000, 600_000, is_64bit=True)
        self.assertEqual(client._session_rx, 200_000)
        self.assertEqual(client._session_tx, 100_000)

        # Reset
        client.reset_session_counters()
        self.assertEqual(client._session_rx, 0)
        self.assertEqual(client._session_tx, 0)

    def test_session_counter_32bit_overflow(self) -> None:
        """Verify 32-bit integer wrap-around (2^32 = 4,294,967,296) is correctly handled."""
        client = FritzUpnpClient()
        max_32 = 4_294_967_296

        # Start close to 32-bit maximum (4 GB)
        client._update_session_counters(max_32 - 1000, 1000, is_64bit=False)

        # Counter overflows to 500 (meaning +1500 bytes flowed)
        client._update_session_counters(500, 1500, is_64bit=False)
        self.assertEqual(client._session_rx, 1500)
        self.assertEqual(client._session_tx, 500)

    def test_discover_endpoints_udn_parsing(self) -> None:
        """Verify extraction of UDN and friendlyName from /igddesc.xml."""
        from unittest.mock import MagicMock, patch

        mock_xml = b"""<?xml version="1.0"?>
        <root xmlns="urn:schemas-upnp-org:device-1-0">
            <device>
                <deviceType>urn:schemas-upnp-org:device:InternetGatewayDevice:1</deviceType>
                <friendlyName>FRITZ!Box 7590</friendlyName>
                <modelName>FRITZ!Box 7590</modelName>
                <UDN>uuid:12345678-0000-0000-0000-001122334455</UDN>
                <serviceList>
                    <service>
                        <serviceType>urn:schemas-upnp-org:service:WANCommonInterfaceConfig:1</serviceType>
                        <controlURL>/igdupnp/control/WANCommonIFC1</controlURL>
                    </service>
                </serviceList>
            </device>
        </root>"""

        client = FritzUpnpClient()
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_xml
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            client._discover_endpoints()
            self.assertEqual(client.box_name, "FRITZ!Box 7590")
            self.assertEqual(client.box_udn, "uuid:12345678-0000-0000-0000-001122334455")
            self.assertEqual(client._common_control_url, "/igdupnp/control/WANCommonIFC1")

    def test_resolve_fritzbox_host_fallback(self) -> None:
        """Verify resolve_fritzbox_host falls back to gateway when public IP is returned."""
        from unittest.mock import patch
        from src.api.upnp_client import resolve_fritzbox_host

        # Custom IP should always be respected as-is
        self.assertEqual(resolve_fritzbox_host("192.168.1.1"), "192.168.1.1")

        # When fritz.box resolves to a public IP (e.g. 198.51.100.1), fall back to detected gateway
        with patch("socket.gethostbyname", return_value="198.51.100.1"):
            with patch("src.api.upnp_client.detect_default_gateway", return_value="192.168.1.1"):
                resolved = resolve_fritzbox_host("fritz.box")
                self.assertEqual(resolved, "192.168.1.1")

        # When fritz.box resolves to a private RFC 1918 IP, keep it
        with patch("socket.gethostbyname", return_value="192.168.178.1"):
            resolved = resolve_fritzbox_host("fritz.box")
            self.assertEqual(resolved, "192.168.178.1")

    def test_fetch_sample_success(self) -> None:
        """Verify fetch_sample parses throughput, link bandwidth, uptime, and WAN status."""
        from unittest.mock import MagicMock, patch

        client = FritzUpnpClient()
        client._wan_conn_control_url = "/igdupnp/control/WANIPConn1"

        def mock_call_common(action: str) -> dict[str, str]:
            if action == "GetAddonInfos":
                return {
                    "NewByteReceiveRate": "125000",
                    "NewByteSendRate": "25000",
                    "NewX_AVM_DE_TotalBytesReceived64": "5000000",
                    "NewX_AVM_DE_TotalBytesSent64": "1000000",
                }
            if action == "GetCommonLinkProperties":
                return {
                    "NewLayer1DownstreamMaxBitRate": "100000000",
                    "NewLayer1UpstreamMaxBitRate": "40000000",
                    "NewPhysicalLinkStatus": "Up",
                }
            return {}

        def mock_soap(url: str, srv: str, action: str) -> dict[str, str]:
            if action == "GetStatusInfo":
                return {"NewConnectionStatus": "Connected", "NewUptime": "3600"}
            if action == "GetExternalIPAddress":
                return {"NewExternalIPAddress": "198.51.100.1"}
            return {}

        with patch.object(client, "_call_common_ifc", side_effect=mock_call_common), \
             patch.object(client, "_soap_call", side_effect=mock_soap):
            sample = client.fetch_sample()
            self.assertTrue(sample.is_connected)
            self.assertTrue(sample.wan_connected)
            self.assertEqual(sample.download_bps, 125000.0)
            self.assertEqual(sample.upload_bps, 25000.0)
            self.assertEqual(sample.max_download_bps, 12500000.0)  # 100 Mbps / 8
            self.assertEqual(sample.max_upload_bps, 5000000.0)  # 40 Mbps / 8
            self.assertEqual(sample.uptime_seconds, 3600)
            self.assertEqual(sample.external_ip, "198.51.100.1")

    def test_fetch_sample_connection_error(self) -> None:
        """Verify fetch_sample returns a safe disconnected sample on network failure."""
        import urllib.error
        from unittest.mock import patch

        client = FritzUpnpClient()
        with patch.object(client, "_call_common_ifc", side_effect=urllib.error.URLError("Connection refused")):
            sample = client.fetch_sample()
            self.assertFalse(sample.is_connected)
            self.assertFalse(sample.wan_connected)
            self.assertFalse(sample.box_reachable)
            self.assertEqual(sample.connection_status, "Nicht erreichbar")
            self.assertIn("Connection refused", sample.error_message)

    def test_soap_call_xml_parsing(self) -> None:
        """Verify _soap_call parses SOAP response envelope into dictionary."""
        from unittest.mock import MagicMock, patch

        mock_soap_xml = b"""<?xml version="1.0"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
            <s:Body>
                <u:GetStatusInfoResponse xmlns:u="urn:schemas-upnp-org:service:WANIPConnection:1">
                    <NewConnectionStatus>Connected</NewConnectionStatus>
                    <NewUptime>7200</NewUptime>
                </u:GetStatusInfoResponse>
            </s:Body>
        </s:Envelope>"""

        client = FritzUpnpClient()
        resp = MagicMock()
        resp.read.return_value = mock_soap_xml
        resp.__enter__.return_value = resp

        with patch("urllib.request.urlopen", return_value=resp):
            data = client._soap_call("/ctrl", "urn:srv", "GetStatusInfo")
            self.assertEqual(data.get("NewConnectionStatus"), "Connected")
            self.assertEqual(data.get("NewUptime"), "7200")


if __name__ == "__main__":
    unittest.main()
