"""Unit tests for api/fritz_monitor.py (AVM TR-064 & Web-API Client)."""

from __future__ import annotations

import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from src.api.fritz_monitor import FritzGuestMonitorClient
from src.api.upnp_client import MAX_RESPONSE_BYTES, _NoRedirectHandler


class TestFritzMonitor(unittest.TestCase):
    """Test AVM authentication, PBKDF2/MD5 challenge-response, guest rates, and counters."""

    def setUp(self) -> None:
        self.client = FritzGuestMonitorClient(
            host="192.168.178.1",
            username="admin",
            password="secret_password",
            timeout=1.0,
        )

    def test_solve_md5_challenge(self) -> None:
        """Verify classic Fritz!OS v1 MD5 challenge calculation."""
        # challenge: "1234567z", password: "test" -> test-vector
        res = FritzGuestMonitorClient._solve_md5_challenge("1234567z", "test")
        self.assertTrue(res.startswith("1234567z-"))
        self.assertEqual(len(res), len("1234567z-") + 32)  # 32 hex chars MD5

    def test_solve_pbkdf2_challenge_invalid(self) -> None:
        """Verify malformed PBKDF2 challenge returns empty string."""
        self.assertEqual(FritzGuestMonitorClient._solve_pbkdf2_challenge("invalid", "test"), "")

    def test_ensure_session_with_existing_sid(self) -> None:
        """When a valid SID already exists, network calls must be skipped."""
        self.client._sid = "abcdef1234567890"
        self.assertTrue(self.client._ensure_session())

    def test_ensure_session_login_flow(self) -> None:
        """Verify two-step PBKDF2 v2 challenge-response authentication against /login_sid.lua."""
        self.client._sid = "0000000000000000"

        # Step 1: PBKDF2 v2 Challenge response
        xml_step1 = b"""<SessionInfo>
            <SID>0000000000000000</SID>
            <Challenge>2$1000$11223344$1000$aabbccdd</Challenge>
            <BlockTime>0</BlockTime>
        </SessionInfo>"""

        # Step 2: Valid SID response
        xml_step2 = b"""<SessionInfo>
            <SID>44556677889900aa</SID>
            <Challenge>2$1000$11223344$1000$aabbccdd</Challenge>
            <BlockTime>0</BlockTime>
        </SessionInfo>"""

        resp1 = MagicMock()
        resp1.read.return_value = xml_step1
        resp1.__enter__.return_value = resp1

        resp2 = MagicMock()
        resp2.read.return_value = xml_step2
        resp2.__enter__.return_value = resp2

        with patch("src.api.fritz_monitor._urlopen_no_redirect", side_effect=[resp1, resp2]):
            ok = self.client._ensure_session()
            self.assertTrue(ok)
            self.assertEqual(self.client._sid, "44556677889900aa")

    def test_ensure_session_blocked(self) -> None:
        """Verify Fritz!Box anti-brute-force BlockTime is respected."""
        self.client._sid = "0000000000000000"
        xml_blocked = b"""<SessionInfo>
            <SID>0000000000000000</SID>
            <Challenge>2$1000$11223344$1000$aabbccdd</Challenge>
            <BlockTime>12</BlockTime>
        </SessionInfo>"""

        resp = MagicMock()
        resp.read.return_value = xml_blocked
        resp.__enter__.return_value = resp

        with patch("src.api.fritz_monitor._urlopen_no_redirect", return_value=resp):
            ok = self.client._ensure_session()
            self.assertFalse(ok)
            self.assertEqual(self.client.last_block_time, 12)
            self.assertIn("12s", self.client.last_error)

    def test_md5_downgrade_blocked_by_default(self) -> None:
        """Verify legacy v1 MD5 challenge is rejected by default unless explicitly enabled."""
        self.client._sid = "0000000000000000"
        xml_v1 = b"""<SessionInfo>
            <SID>0000000000000000</SID>
            <Challenge>1234567z</Challenge>
            <BlockTime>0</BlockTime>
        </SessionInfo>"""
        resp = MagicMock()
        resp.read.return_value = xml_v1
        resp.__enter__.return_value = resp

        with patch("src.api.fritz_monitor._urlopen_no_redirect", return_value=resp) as mock_open:
            ok = self.client._ensure_session()
            self.assertFalse(ok)
            self.assertIn("MD5", self.client.last_error)
            self.assertEqual(mock_open.call_count, 1)

    def test_pbkdf2_excessive_iterations_rejected(self) -> None:
        """Verify PBKDF2 challenges outside [MIN_PBKDF2_ITERATIONS, MAX_PBKDF2_ITERATIONS] or invalid salts are rejected."""
        self.assertEqual(FritzGuestMonitorClient._solve_pbkdf2_challenge("2$100001$1122$1000$aabb", "pw"), "")
        self.assertEqual(FritzGuestMonitorClient._solve_pbkdf2_challenge("2$1000$1122$100001$aabb", "pw"), "")
        self.assertEqual(FritzGuestMonitorClient._solve_pbkdf2_challenge("2$999$1122$1000$aabb", "pw"), "")
        self.assertEqual(FritzGuestMonitorClient._solve_pbkdf2_challenge("2$1000$1122$5$aabb", "pw"), "")
        self.assertEqual(FritzGuestMonitorClient._solve_pbkdf2_challenge("2$0$1122$1000$aabb", "pw"), "")
        self.assertEqual(FritzGuestMonitorClient._solve_pbkdf2_challenge("2$1000$zzzz$1000$aabb", "pw"), "")

    def test_redirect_blocked(self) -> None:
        """Verify _NoRedirectHandler rejects HTTP 3xx redirects without following."""
        handler = _NoRedirectHandler()
        req = urllib.request.Request("http://192.168.178.1/login_sid.lua?version=2")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            handler.redirect_request(req, None, 302, "Found", {}, "http://evil.invalid/")
        self.assertIn("redirects are disabled", str(ctx.exception))

    def test_oversized_response_rejected(self) -> None:
        """Verify HTTP responses larger than MAX_RESPONSE_BYTES are aborted safely."""
        self.client._sid = "0000000000000000"
        resp = MagicMock()
        resp.read.return_value = b"A" * (MAX_RESPONSE_BYTES + 1)
        resp.__enter__.return_value = resp

        with patch("src.api.fritz_monitor._urlopen_no_redirect", return_value=resp):
            ok = self.client._ensure_session()
            self.assertFalse(ok)
            self.assertIn("limit", self.client.last_error.lower())

    def test_logout_clears_sid(self) -> None:
        """Verify logout() calls login_sid.lua with logout=1 and resets cached SID."""
        self.client._sid = "44556677889900aa"
        resp = MagicMock()
        resp.__enter__.return_value = resp

        with patch("src.api.fritz_monitor._urlopen_no_redirect", return_value=resp) as mock_open:
            self.client.logout()
            self.assertEqual(self.client._sid, "0000000000000000")
            mock_open.assert_called_once()
            req_arg = mock_open.call_args[0][0]
            self.assertIn("logout=1", req_arg.data.decode("utf-8"))
            self.assertIn("44556677889900aa", req_arg.data.decode("utf-8"))

    def test_fetch_online_counters_success(self) -> None:
        """Verify parsing of online counters high/low bytes into OnlineCounterStats."""
        self.client._sid = "authenticated_sid"

        mock_json_data = json.dumps({
            "TodaySentHigh": 0,
            "TodaySentLow": 1500000,
            "TodayRecvHigh": 0,
            "TodayRecvLow": 8500000,
            "YesterdaySentHigh": 0,
            "YesterdaySentLow": 2000000,
            "YesterdayRecvHigh": 0,
            "YesterdayRecvLow": 12000000,
            "WeekSentHigh": 0,
            "WeekSentLow": 10000000,
            "WeekRecvHigh": 0,
            "WeekRecvLow": 50000000,
            "MonthSentHigh": 1,
            "MonthSentLow": 0,  # 1 * 2^32 = 4,294,967,296 bytes
            "MonthRecvHigh": 2,
            "MonthRecvLow": 1000,
            "LastMonthSentHigh": 0,
            "LastMonthSentLow": 3000000,
            "LastMonthRecvHigh": 0,
            "LastMonthRecvLow": 9000000,
        }).encode("utf-8")

        resp = MagicMock()
        resp.read.return_value = mock_json_data
        resp.__enter__.return_value = resp

        with patch("src.api.fritz_monitor._urlopen_no_redirect", return_value=resp):
            stats = self.client.fetch_online_counters()
            self.assertTrue(stats.is_available)
            self.assertEqual(stats.today.sent_bytes, 1500000)
            self.assertEqual(stats.today.received_bytes, 8500000)
            self.assertEqual(stats.this_month.sent_bytes, 4294967296)

    def test_fetch_guest_rates_bps_success(self) -> None:
        """Verify extraction of guest network download & upload rates from data.lua."""
        self.client._sid = "authenticated_sid"

        mock_json_data = json.dumps({
            "data": {
                "sync_groups": [
                    {
                        "ds_guest_bps": [50000, 45000],
                        "us_guest_bps": [12000, 11000],
                    }
                ]
            }
        }).encode("utf-8")

        resp = MagicMock()
        resp.read.return_value = mock_json_data
        resp.__enter__.return_value = resp

        with patch("src.api.fritz_monitor._urlopen_no_redirect", return_value=resp):
            ds, us, active = self.client.fetch_guest_rates_bps()
            self.assertTrue(active)
            self.assertEqual(ds, 50000.0)
            self.assertEqual(us, 12000.0)


if __name__ == "__main__":
    unittest.main()
