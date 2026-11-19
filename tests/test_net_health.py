"""Unit tests for api/net_health.py."""

from __future__ import annotations

import socket
import ssl
import struct
from unittest.mock import MagicMock, patch
import unittest

from src.api.net_health import (
    NetworkHealthMonitor,
    _measure_ping_linux_icmp,
    _parse_dns_response,
    detect_active_os_dns,
    measure_dns_query,
    measure_https_canary,
    measure_ping,
    measure_uncached_dns,
    parse_ping_output,
    set_shutting_down,
)


def _build_dns_reply(tx_id: bytes, rcode: int, answer_ip: str | None = None) -> bytes:
    """Build a minimal RFC 1035 DNS UDP response packet for unit tests."""
    flags = 0x8180 | (rcode & 0x0F)
    ancount = 1 if (rcode == 0 and answer_ip) else 0
    header = tx_id + struct.pack("!HHHHH", flags, 1, ancount, 0, 0)
    question = b"\x04test\x07example\x00\x00\x01\x00\x01"
    if ancount == 0 or not answer_ip:
        return header + question
    # Pointer 0xC00C -> question QNAME, TYPE=A, CLASS=IN, TTL=60, RDLENGTH=4
    answer = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + socket.inet_aton(answer_ip)
    return header + question + answer


class TestNetHealth(unittest.TestCase):
    """Test network diagnostics: ping parsing, in-process ICMP, jitter EMA, and shutdown guards."""

    def setUp(self) -> None:
        set_shutting_down(False)

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

    def test_ping_rejects_flag_injection_host(self) -> None:
        """Verify measure_ping rejects hosts starting with '-' or containing shell/URL chars."""
        with patch("src.api.net_health.subprocess.run") as mock_subproc, patch(
            "src.api.net_health._measure_ping_windows_icmp"
        ) as mock_win, patch("src.api.net_health._measure_ping_linux_icmp") as mock_lin:
            for bad in ("-i 0.1 1.1.1.1", "--help", "1.1.1.1;whoami", "evil.invalid/path"):
                self.assertIsNone(measure_ping(bad))
            mock_subproc.assert_not_called()
            mock_win.assert_not_called()
            mock_lin.assert_not_called()

    def test_linux_ping_fallback_uses_double_dash(self) -> None:
        """Verify Linux CLI ping fallback passes '--' before target_host."""
        mock_res = MagicMock(returncode=0, stdout=b"64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=9.5 ms\n")
        with (
            patch("src.api.net_health.sys.platform", "linux"),
            patch("src.api.net_health._measure_ping_linux_icmp", return_value=None),
            patch("src.api.net_health.subprocess.run", return_value=mock_res) as mock_subproc,
        ):
            res = measure_ping("1.1.1.1")
            self.assertEqual(res, 9.5)
            cmd = mock_subproc.call_args[0][0]
            self.assertEqual(cmd, ["ping", "-c", "1", "-W", "1", "--", "1.1.1.1"])

    def test_dns_response_rcode_and_hijack_validation(self) -> None:
        """Verify NOERROR, NXDOMAIN, SERVFAIL, REFUSED, and private-IP hijack detection."""
        tx = b"\x12\x34"
        valid, rcode, answers = _parse_dns_response(_build_dns_reply(tx, 0, "93.184.216.34"), tx)
        self.assertTrue(valid)
        self.assertEqual(rcode, 0)
        self.assertEqual(answers, ("93.184.216.34",))

        def _run_with_rcode(rc: int, ip: str | None = None, **query_kwargs):
            mock_sock = MagicMock()

            def _fake_sendto(pkt: bytes, addr: tuple[str, int]) -> int:
                mock_sock.recvfrom.return_value = (_build_dns_reply(pkt[:2], rc, ip), ("192.168.178.2", 53))
                return len(pkt)

            mock_sock.sendto.side_effect = _fake_sendto
            with patch("src.api.net_health.socket.socket", return_value=mock_sock):
                return measure_dns_query("192.168.178.2", domain="test.example", **query_kwargs)

        res_ok = _run_with_rcode(0, "93.184.216.34", reject_private_answers=True)
        self.assertTrue(res_ok.ok)
        self.assertEqual(res_ok.answers, ("93.184.216.34",))

        res_nx_ok = _run_with_rcode(3, accept_nxdomain=True)
        self.assertTrue(res_nx_ok.ok)
        self.assertEqual(res_nx_ok.rcode, 3)

        res_nx_fail = _run_with_rcode(3, accept_nxdomain=False)
        self.assertFalse(res_nx_fail.ok)
        self.assertEqual(res_nx_fail.error, "nxdomain")

        self.assertEqual(_run_with_rcode(2).error, "servfail")
        self.assertEqual(_run_with_rcode(5).error, "refused")
        self.assertEqual(_run_with_rcode(0, "192.168.178.1", reject_private_answers=True).error, "hijacked")
        self.assertEqual(_run_with_rcode(0, "0.0.0.0", reject_private_answers=True).error, "hijacked")

    def test_measure_uncached_dns_generates_unique_nonces(self) -> None:
        """Verify measure_uncached_dns sends randomized nonce subdomains with accept_nxdomain=True."""
        seen_domains: list[str] = []

        def fake_query(dns_server: str, domain: str, **kwargs):
            seen_domains.append(domain)
            self.assertTrue(kwargs.get("accept_nxdomain"))
            self.assertTrue(kwargs.get("reject_private_answers"))
            return MagicMock(ok=True, latency_ms=11.0, rcode=3, error="")

        with patch("src.api.net_health.measure_dns_query", side_effect=fake_query):
            measure_uncached_dns("192.168.178.2")
            measure_uncached_dns("192.168.178.2")

        self.assertEqual(len(seen_domains), 2)
        self.assertNotEqual(seen_domains[0], seen_domains[1])
        self.assertTrue(seen_domains[0].startswith("tb-"))
        self.assertTrue(seen_domains[0].endswith(".tbcheck.cloudflare.com"))

    def test_https_canary_204_captive_portal_tls_and_timeout(self) -> None:
        """Verify measure_https_canary classifies 204 OK, 302 captive portal, SSL error, and timeout."""
        def _run_canary(response_bytes: bytes | None = None, wrap_exc: Exception | None = None, conn_exc: Exception | None = None):
            mock_raw = MagicMock()
            mock_tls = MagicMock()
            if conn_exc is not None:
                mock_raw.connect.side_effect = conn_exc
            if wrap_exc is not None:
                mock_ctx = MagicMock()
                mock_ctx.wrap_socket.side_effect = wrap_exc
            else:
                mock_ctx = MagicMock()
                mock_ctx.wrap_socket.return_value = mock_tls
                mock_tls.recv.return_value = response_bytes or b"HTTP/1.1 204 No Content\r\n\r\n"

            with (
                patch("src.api.net_health.socket.socket", return_value=mock_raw),
                patch("src.api.net_health._get_default_ssl_context", return_value=mock_ctx),
            ):
                return measure_https_canary("198.51.100.1", "cp.cloudflare.com", "/generate_204")

        r_ok = _run_canary(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
        self.assertTrue(r_ok.ok)
        self.assertEqual(r_ok.status_code, 204)

        r_captive = _run_canary(b"HTTP/1.1 302 Found\r\nLocation: http://portal.local\r\n\r\n")
        self.assertFalse(r_captive.ok)
        self.assertEqual(r_captive.error, "captive_portal")
        self.assertEqual(r_captive.status_code, 302)

        r_tls = _run_canary(wrap_exc=ssl.SSLError("cert mismatch"))
        self.assertFalse(r_tls.ok)
        self.assertEqual(r_tls.error, "tls_error")

        r_timeout = _run_canary(conn_exc=TimeoutError("timed out"))
        self.assertFalse(r_timeout.ok)
        self.assertEqual(r_timeout.error, "timeout")

    def test_windows_detect_dns_prefers_iphlpapi_over_winreg(self) -> None:
        """Verify Windows DNS detection uses active iphlpapi DNS before winreg adapter fallback."""
        with (
            patch("src.api.net_health.sys.platform", "win32"),
            patch("src.api.net_health._detect_windows_dns_iphlpapi", return_value="192.168.178.2") as mock_iph,
            patch("winreg.OpenKey") as mock_reg,
        ):
            self.assertEqual(detect_active_os_dns(), "192.168.178.2")
            mock_iph.assert_called_once()
            mock_reg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
