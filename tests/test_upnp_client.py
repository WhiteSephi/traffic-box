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


if __name__ == "__main__":
    unittest.main()
