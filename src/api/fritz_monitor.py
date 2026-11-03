"""Optional authenticated Fritz!OS Online-Monitor client for Guest Wi-Fi traffic share."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


class FritzGuestMonitorClient:
    """Queries Fritz!OS login_sid.lua & netMoni to extract Guest network traffic share."""

    def __init__(
        self,
        host: str = "fritz.box",
        username: str = "",
        password: str = "",
        timeout: float = 2.0,
    ) -> None:
        self.host = host.strip() or "fritz.box"
        self.username = username.strip()
        self.password = password
        self.timeout = timeout
        self._sid: str = "0000000000000000"

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
            return False
        if self._sid and self._sid != "0000000000000000":
            return True

        url = f"http://{self.host}/login_sid.lua?version=2"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                xml_bytes = resp.read()
            root = ET.fromstring(xml_bytes)
            sid = (root.findtext("SID") or "").strip()
            if sid and sid != "0000000000000000":
                self._sid = sid
                return True

            challenge = (root.findtext("Challenge") or "").strip()
            if not challenge:
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
            req = urllib.request.Request(url, data=form_data, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp2:
                xml_bytes2 = resp2.read()
            root2 = ET.fromstring(xml_bytes2)
            sid2 = (root2.findtext("SID") or "").strip()
            if sid2 and sid2 != "0000000000000000":
                self._sid = sid2
                return True
        except (urllib.error.URLError, ET.ParseError, TimeoutError, OSError, ValueError):
            self._sid = "0000000000000000"
        return False

    @staticmethod
    def _first_numeric_value(val: object) -> float:
        """Extract the latest numeric value (bits or bytes per sec) from Fritz!OS series."""
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

        # If session expired, Fritz!OS returns pid="logout" or no data
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

        # Fritz!OS reports ds_guest_bps / us_guest_bps (or guest_ds_bps) in bytes/sec or bits/sec
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

        # Note: In Fritz!OS netMoni, *_bps arrays are actually bytes per second (despite the name)
        # just like ds_current_bps; we return them as float >= 0.0
        return (max(0.0, ds_guest), max(0.0, us_guest), True)
