"""Authenticated Fritz!OS client for Online-Zähler (query.lua) & Guest Wi-Fi traffic (netMoni)."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from src.api.models import OnlineCounterStats, PeriodCounter


class FritzGuestMonitorClient:
    """Queries Fritz!OS login_sid.lua, query.lua (Online-Zähler) & data.lua (netMoni)."""

    def __init__(
        self,
        host: str = "fritz.box",
        username: str = "",
        password: str = "",
        timeout: float = 3.5,
    ) -> None:
        self.host = host.strip() or "fritz.box"
        self.username = username.strip()
        self.password = password
        self.timeout = timeout
        self._sid: str = "0000000000000000"
        self.last_error: str = ""
        self.last_block_time: int = 0
        self._next_attempt_time: float = 0.0

    def update_credentials(self, host: str, username: str, password: str) -> None:
        """Update host or credentials and invalidate cached SID if changed."""
        clean_host = host.strip() or "fritz.box"
        clean_user = username.strip()
        if (
            clean_host != self.host
            or clean_user != self.username
            or password != self.password
        ):
            self.host = clean_host
            self.username = clean_user
            self.password = password
            self._sid = "0000000000000000"
            self.last_error = ""
            self.last_block_time = 0
            self._next_attempt_time = 0.0

    @property
    def is_configured(self) -> bool:
        """Return True if a Fritz!Box password is set."""
        return bool(self.password)

    @staticmethod
    def _solve_pbkdf2_challenge(challenge: str, password: str) -> str:
        """Solve Fritz!OS v2 PBKDF2 challenge (2$iter1$salt1$iter2$salt2)."""
        parts = challenge.split("$")
        if len(parts) < 5:
            return ""
        iter1 = int(parts[1])
        salt1 = bytes.fromhex(parts[2])
        iter2 = int(parts[3])
        salt2 = bytes.fromhex(parts[4])

        hash1 = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt1, iter1)
        hash2 = hashlib.pbkdf2_hmac("sha256", hash1, salt2, iter2)
        return f"{parts[4]}${hash2.hex()}"

    @staticmethod
    def _solve_md5_challenge(challenge: str, password: str) -> str:
        """Solve classic Fritz!OS v1 MD5 challenge."""
        cleaned = "".join(ch if ord(ch) < 256 else "." for ch in f"{challenge}-{password}")
        digest = hashlib.md5(cleaned.encode("utf-16-le")).hexdigest()
        return f"{challenge}-{digest}"

    def _ensure_session(self) -> bool:
        """Authenticate against /login_sid.lua?version=2 if SID is missing or invalid."""
        if not self.is_configured:
            self.last_error = "Kein Passwort konfiguriert"
            return False
        if self._sid and self._sid != "0000000000000000":
            return True

        now = time.monotonic()
        if now < self._next_attempt_time:
            # Active cooldown protection: do not spam the Fritz!Box to protect user account
            remaining = int(self._next_attempt_time - now)
            self.last_error = f"Fritz!Box Sperrzeit aktiv: Bitte noch {remaining}s warten."
            return False

        url = f"http://{self.host}/login_sid.lua?version=2"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                xml_bytes = resp.read()
            root = ET.fromstring(xml_bytes)
            sid = (root.findtext("SID") or "").strip()
            if sid and sid != "0000000000000000":
                self._sid = sid
                self.last_error = ""
                self.last_block_time = 0
                return True

            block_time = int(root.findtext("BlockTime") or "0")
            if block_time > 0:
                self.last_block_time = block_time
                self.last_error = f"Fritz!Box Sperrzeit aktiv ({block_time}s)"
                self._next_attempt_time = now + block_time
                return False

            challenge = (root.findtext("Challenge") or "").strip()
            if not challenge:
                self.last_error = "Keine Challenge von Fritz!Box erhalten"
                return False

            # If no username was provided, inspect Default/Users tag from SessionInfo
            user = self.username
            if not user:
                for user_elem in root.iter("User"):
                    if user_elem.text:
                        user = user_elem.text.strip()
                        if user_elem.attrib.get("last") == "1":
                            break

            if challenge.startswith("2$"):
                response_str = self._solve_pbkdf2_challenge(challenge, self.password)
            else:
                response_str = self._solve_md5_challenge(challenge, self.password)

            form_data = urllib.parse.urlencode(
                {"username": user, "response": response_str}
            ).encode("utf-8")
            post_timeout = max(self.timeout, float(block_time + 4))
            req = urllib.request.Request(url, data=form_data, method="POST")
            with urllib.request.urlopen(req, timeout=post_timeout) as resp2:
                xml_bytes2 = resp2.read()
            root2 = ET.fromstring(xml_bytes2)
            sid2 = (root2.findtext("SID") or "").strip()
            block_time2 = int(root2.findtext("BlockTime") or "0")
            self.last_block_time = block_time2

            if sid2 and sid2 != "0000000000000000":
                self._sid = sid2
                self.last_error = ""
                self._next_attempt_time = 0.0
                return True
            else:
                self._sid = "0000000000000000"
                self.last_error = "Fritz!Box Passwort oder Benutzername falsch"
                # Cooldown: wait at least 30s or block_time2 + 5s to prevent account lockout
                cooldown_sec = max(30.0, float(block_time2 + 5.0))
                self._next_attempt_time = time.monotonic() + cooldown_sec
                return False
        except (urllib.error.URLError, ET.ParseError, TimeoutError, OSError, ValueError) as exc:
            self._sid = "0000000000000000"
            self.last_error = f"Verbindungsfehler: {exc}"
            self._next_attempt_time = time.monotonic() + 15.0
            return False

    def test_login(self) -> tuple[bool, str, int]:
        """Test authentication against Fritz!OS and return (success, message, block_time)."""
        self._next_attempt_time = 0.0
        self._sid = "0000000000000000"
        ok = self._ensure_session()
        if ok:
            return True, "Fritz!OS Login erfolgreich (SID erhalten)", 0
        if self.last_block_time > 0:
            return False, f"Fritz!Box Sperrzeit aktiv: Bitte noch {self.last_block_time} Sekunden warten.", self.last_block_time
        if self.last_error:
            return False, self.last_error, 0
        return False, "Login fehlgeschlagen (Passwort oder Host prüfen)", 0

    @staticmethod
    def _first_numeric_value(val: object) -> float:
        """Extract the latest numeric value from Fritz!OS series."""
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, list) and val:
            try:
                return float(val[0])
            except (ValueError, TypeError):
                return 0.0
        if isinstance(val, str):
            first = val.split(",")[0].strip()
            try:
                return float(first)
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def _combine_high_low(data: dict[str, object], prefix: str, direction: str) -> int:
        """Combine 32-bit High and Low counters from inetstat into a 64-bit integer."""
        try:
            high = int(str(data.get(f"{prefix}{direction}High", "0") or "0"))
            low = int(str(data.get(f"{prefix}{direction}Low", "0") or "0"))
            return (high << 32) + low
        except ValueError:
            return 0

    def fetch_online_counters(self) -> OnlineCounterStats:
        """Fetch Fritz!Box Online-Zähler (Heute, Gestern, Woche, Monat, Vormonat) via query.lua."""
        stats = OnlineCounterStats()
        if not self._ensure_session():
            return stats

        periods = [
            ("Today", "Today"),
            ("Yesterday", "Yesterday"),
            ("Week", "ThisWeek"),
            ("Month", "ThisMonth"),
            ("LastMonth", "LastMonth"),
        ]
        params: dict[str, str] = {"sid": self._sid}
        for short, f_key in periods:
            params[f"{short}SentHigh"] = f"inetstat:status/{f_key}/BytesSentHigh"
            params[f"{short}SentLow"] = f"inetstat:status/{f_key}/BytesSentLow"
            params[f"{short}RecvHigh"] = f"inetstat:status/{f_key}/BytesReceivedHigh"
            params[f"{short}RecvLow"] = f"inetstat:status/{f_key}/BytesReceivedLow"

        query_str = urllib.parse.urlencode(params)
        url = f"http://{self.host}/query.lua?{query_str}"

        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw_json = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw_json)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
            self._sid = "0000000000000000"
            return stats

        if not isinstance(data, dict) or "TodaySentLow" not in data:
            self._sid = "0000000000000000"
            return stats

        stats.today = PeriodCounter(
            received_bytes=self._combine_high_low(data, "Today", "Recv"),
            sent_bytes=self._combine_high_low(data, "Today", "Sent"),
        )
        stats.yesterday = PeriodCounter(
            received_bytes=self._combine_high_low(data, "Yesterday", "Recv"),
            sent_bytes=self._combine_high_low(data, "Yesterday", "Sent"),
        )
        stats.this_week = PeriodCounter(
            received_bytes=self._combine_high_low(data, "Week", "Recv"),
            sent_bytes=self._combine_high_low(data, "Week", "Sent"),
        )
        stats.this_month = PeriodCounter(
            received_bytes=self._combine_high_low(data, "Month", "Recv"),
            sent_bytes=self._combine_high_low(data, "Month", "Sent"),
        )
        stats.last_month = PeriodCounter(
            received_bytes=self._combine_high_low(data, "LastMonth", "Recv"),
            sent_bytes=self._combine_high_low(data, "LastMonth", "Sent"),
        )
        stats.is_available = True
        return stats

    def fetch_guest_rates_bps(self) -> tuple[float, float, bool]:
        """Return (guest_download_bps, guest_upload_bps, guest_active) in bytes/sec."""
        if not self._ensure_session():
            return (0.0, 0.0, False)

        url = f"http://{self.host}/data.lua"
        payload = urllib.parse.urlencode(
            {
                "xhr": "1",
                "sid": self._sid,
                "lang": "de",
                "page": "netMoni",
                "xhrId": "updateGraphs",
                "useajax": "1",
                "no_sidrenew": "",
            }
        ).encode("utf-8")

        try:
            req = urllib.request.Request(url, data=payload, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw_json = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw_json)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
            self._sid = "0000000000000000"
            return (0.0, 0.0, False)

        if not isinstance(data, dict) or "data" not in data:
            self._sid = "0000000000000000"
            return (0.0, 0.0, False)

        inner = data.get("data", {})
        if not isinstance(inner, dict):
            return (0.0, 0.0, False)

        sync_groups = inner.get("sync_groups") or []
        group = sync_groups[0] if isinstance(sync_groups, list) and sync_groups else inner
        if not isinstance(group, dict):
            return (0.0, 0.0, False)

        ds_guest = (
            self._first_numeric_value(group.get("ds_guest_bps"))
            or self._first_numeric_value(group.get("guest_ds_bps"))
            or self._first_numeric_value(group.get("ds_guest"))
        )
        us_guest = (
            self._first_numeric_value(group.get("us_guest_bps"))
            or self._first_numeric_value(group.get("guest_us_bps"))
            or self._first_numeric_value(group.get("us_guest"))
        )

        return (max(0.0, ds_guest), max(0.0, us_guest), True)
