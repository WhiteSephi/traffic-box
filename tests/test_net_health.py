"""Unit tests for api/net_health.py."""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch
import unittest

from src.api.net_health import NetworkHealthMonitor, measure_ping


class TestNetHealth(unittest.TestCase):
    """Test network diagnostics: ping regex, jitter EMA, and monitoring logic."""

    def test_ping_regex_windows_german(self) -> None:
        """Verify Windows German ping parsing matches Zeit=XXms."""
        output = (
            "Ping wird ausgefuehrt fuer 1.1.1.1 mit 32 Bytes Daten:\n"
            "Antwort von 1.1.1.1: Bytes=32 Zeit=14ms TTL=57\n"
        )
        match = re.search(r"(?:Zeit|time)[=<]\s*(\d+(?:\.\d+)?)\s*ms", output, re.IGNORECASE)
        self.assertIsNotNone(match)
        self.assertEqual(float(match.group(1)), 14.0)

    def test_ping_regex_linux(self) -> None:
        """Verify Linux ping parsing matches time=XX.X ms."""
        output = (
            "PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.\n"
            "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=11.8 ms\n"
        )
        match = re.search(r"(?:Zeit|time)[=<]\s*(\d+(?:\.\d+)?)\s*ms", output, re.IGNORECASE)
        self.assertIsNotNone(match)
        self.assertEqual(float(match.group(1)), 11.8)

    def test_ping_regex_sub_millisecond(self) -> None:
        """Verify Zeit<1ms is captured correctly."""
        output = "Antwort von 192.168.178.1: Bytes=32 Zeit<1ms TTL=64\n"
        match = re.search(r"(?:Zeit|time)[=<]\s*(\d+(?:\.\d+)?)\s*ms", output, re.IGNORECASE)
        self.assertIsNotNone(match)
        self.assertEqual(float(match.group(1)), 1.0)

    def test_jitter_ema_calculation(self) -> None:
        """Verify rolling jitter EMA calculation on successive pings."""
        monitor = NetworkHealthMonitor(endpoint="1.1.1.1")

        with patch("src.api.net_health.measure_ping", side_effect=[10.0, 20.0, 15.0]):
            # First tick: ping 10.0 -> initial jitter is 0.0
            p1, j1, _, _ = monitor.tick(check_ping=True, check_dns=False)
            self.assertEqual(p1, 10.0)
            self.assertEqual(j1, 0.0)

            # Second tick: ping 20.0 -> diff = 10.0. Jitter = 0.0 * 0.6 + 10.0 * 0.4 = 4.0
            p2, j2, _, _ = monitor.tick(check_ping=True, check_dns=False)
            self.assertEqual(p2, 20.0)
            self.assertEqual(j2, 4.0)

            # Third tick: ping 15.0 -> diff = 5.0. Jitter = 4.0 * 0.6 + 5.0 * 0.4 = 2.4 + 2.0 = 4.4
            p3, j3, _, _ = monitor.tick(check_ping=True, check_dns=False)
            self.assertEqual(p3, 15.0)
            self.assertEqual(j3, 4.4)


if __name__ == "__main__":
    unittest.main()
