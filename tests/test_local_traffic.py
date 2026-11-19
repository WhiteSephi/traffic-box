"""Unit tests for api/local_traffic.py."""

from __future__ import annotations

import ctypes
import sys
from unittest.mock import mock_open, patch
import unittest

from src.api.local_traffic import LocalTrafficMonitor, _read_linux_adapter_bytes


class TestLocalTraffic(unittest.TestCase):
    """Test local network interface traffic measurement."""

    def test_parse_linux_proc_net_dev(self) -> None:
        """Verify parsing of /proc/net/dev lines, skipping lo and docker."""
        sample_proc_data = (
            "Inter-|   Receive                                                |  Transmit\n"
            " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
            "    lo: 1234567       0    0    0    0     0          0         0  1234567       0    0    0    0     0       0          0\n"
            "docker0: 999999       0    0    0    0     0          0         0   999999       0    0    0    0     0       0          0\n"
            "  eth0: 50000000   1000    0    0    0     0          0         0 10000000    1000    0    0    0     0       0          0\n"
            " wlan0: 25000000    500    0    0    0     0          0         0  5000000     500    0    0    0     0       0          0\n"
        )
        with patch("builtins.open", mock_open(read_data=sample_proc_data)):
            rx, tx, ok = _read_linux_adapter_bytes()
            self.assertTrue(ok)
            # eth0 (50M rx, 10M tx) + wlan0 (25M rx, 5M tx) = 75M rx, 15M tx (lo and docker0 ignored)
            self.assertEqual(rx, 75_000_000)
            self.assertEqual(tx, 15_000_000)

    def test_rate_calculation_delta(self) -> None:
        """Verify rate delta math in LocalTrafficMonitor."""
        monitor = LocalTrafficMonitor()

        # Step 1: Initial reading (returns 0.0, 0.0)
        with patch("src.api.local_traffic.time.monotonic", return_value=100.0):
            with patch("src.api.local_traffic._read_windows_adapter_bytes", return_value=(1000, 500, True)):
                with patch("src.api.local_traffic._read_linux_adapter_bytes", return_value=(1000, 500, True)):
                    down, up, ok = monitor.fetch_rates_bps()
                    self.assertTrue(ok)
                    self.assertEqual(down, 0.0)
                    self.assertEqual(up, 0.0)

        # Step 2: 1.0 second later, 10,000 bytes down, 5,000 bytes up
        with patch("src.api.local_traffic.time.monotonic", return_value=101.0):
            with patch("src.api.local_traffic._read_windows_adapter_bytes", return_value=(11000, 5500, True)):
                with patch("src.api.local_traffic._read_linux_adapter_bytes", return_value=(11000, 5500, True)):
                    down, up, ok = monitor.fetch_rates_bps()
                    self.assertTrue(ok)
                    self.assertAlmostEqual(down, 10000.0, places=1)
                    self.assertAlmostEqual(up, 5000.0, places=1)
                    self.assertEqual(monitor.session_bytes_received, 10000)
                    self.assertEqual(monitor.session_bytes_sent, 5000)

        # Step 3: Reset session counters
        monitor.reset_session_counters()
        self.assertEqual(monitor.session_bytes_received, 0)
        self.assertEqual(monitor.session_bytes_sent, 0)

    def test_windows_mib_if_row2_struct_size(self) -> None:
        """Verify _MIB_IF_ROW2 matches Windows x64 MIB_IF_ROW2 struct size (1352 bytes)."""
        if sys.platform != "win32":
            return
        from src.api.local_traffic import _MIB_IF_ROW2

        self.assertEqual(ctypes.sizeof(_MIB_IF_ROW2), 1352)


if __name__ == "__main__":
    unittest.main()
