"""Unit tests for api/net_health.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import unittest

from src.api.net_health import (
    NetworkHealthMonitor,
    _measure_ping_linux_icmp,
    measure_ping,
    parse_ping_output,
    set_shutting_down,
)


class TestNetHealth(unittest.TestCase):
    """Test network diagnostics: ping parsing, in-process ICMP, jitter EMA, and shutdown guards."""

    def tearDown(self) -> None:
        set_shutting_down(False)

    def test_ping_regex_windows_german(self) -> None:
        """Verify Windows German ping parsing matches Zeit=XXms."""
        output = (
            "Ping wird ausgefuehrt fuer 1.1.1.1 mit 32 Bytes Daten:\n"
            "Antwort von 1.1.1.1: Bytes=32 Zeit=14ms TTL=57\n"
        )
        self.assertEqual(parse_ping_output(output), 14.0)

    def test_ping_regex_linux(self) -> None:
        """Verify Linux ping parsing matches time=XX.X ms."""
        output = (
            "PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.\n"
            "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=11.8 ms\n"
        )
        self.assertEqual(parse_ping_output(output), 11.8)

    def test_ping_regex_sub_millisecond(self) -> None:
        """Verify Zeit<1ms is captured correctly."""
        output = "Antwort von 192.168.178.1: Bytes=32 Zeit<1ms TTL=64\n"
        self.assertEqual(parse_ping_output(output), 1.0)

    def test_windows_ping_never_spawns_subprocess(self) -> None:
        """Ensure Windows measure_ping uses in-process APIs and never spawns ping.exe."""
        with (
            patch("src.api.net_health.sys.platform", "win32"),
            patch("src.api.net_health.subprocess.run") as mock_subproc,
            patch("src.api.net_health._measure_ping_windows_icmp", return_value=12.3),
        ):
            res = measure_ping("1.1.1.1")
            self.assertEqual(res, 12.3)
            mock_subproc.assert_not_called()

    def test_linux_in_process_icmp_socket(self) -> None:
        """Verify Linux unprivileged SOCK_DGRAM ICMP socket measurement."""
        mock_sock = MagicMock()
        # Type 0 = ICMP_ECHOREPLY, 8+ bytes
        mock_sock.recvfrom.return_value = (b"\x00\x00\x00\x00\x00\x01\x00\x01TrafficBoxPing16", ("1.1.1.1", 0))
        with (
            patch("src.api.net_health.sys.platform", "linux"),
            patch("src.api.net_health.socket.gethostbyname", return_value="1.1.1.1"),
            patch("src.api.net_health.socket.socket", return_value=mock_sock),
        ):
            res = _measure_ping_linux_icmp("1.1.1.1", timeout_ms=500)
            self.assertIsNotNone(res)
            self.assertGreaterEqual(res, 0.1)
            mock_sock.close.assert_called_once()

    def test_shutting_down_guard_aborts_diagnostics(self) -> None:
        """Verify measure_ping immediately returns None when shutting down."""
        set_shutting_down(True)
        with patch("src.api.net_health._measure_ping_windows_icmp") as mock_win:
            self.assertIsNone(measure_ping("1.1.1.1"))
            mock_win.assert_not_called()

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
