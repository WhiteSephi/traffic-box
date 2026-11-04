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


if __name__ == "__main__":
    unittest.main()
