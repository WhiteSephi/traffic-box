"""Unit tests for privacy-preserving logging and diagnostics helpers."""

from __future__ import annotations

from pathlib import Path
import unittest

from src.config import AppConfig
from src.logger import (
    MAX_ISSUE_BODY_CHARS,
    build_github_issue_url,
    collect_diagnostics_report,
    redact_sensitive_text,
)


class LoggerTests(unittest.TestCase):
    """Verify redaction filter, diagnostics report generation, and issue URL builder."""

    def test_redact_sensitive_text_masks_home_ips_and_secrets(self) -> None:
        home_sample = str(Path.home() / "Documents" / "secret.txt")
        raw = (
            f"path={home_sample} peer=192.0.2.42 default=192.168.178.1 "
            "dns=1.1.1.1 local=127.0.0.1 sid=deadbeef1234 password=changeme"
        )
        redacted = redact_sensitive_text(raw)

        self.assertNotIn(str(Path.home()), redacted)
        self.assertIn("~", redacted)
        self.assertNotIn("192.0.2.42", redacted)
        self.assertIn("peer=<IP>", redacted)
        self.assertIn("192.168.178.1", redacted)
        self.assertIn("1.1.1.1", redacted)
        self.assertIn("127.0.0.1", redacted)
        self.assertNotIn("deadbeef1234", redacted)
        self.assertNotIn("changeme", redacted)
        self.assertIn("sid=***", redacted)
        self.assertIn("password=***", redacted)

    def test_collect_diagnostics_report_excludes_credentials(self) -> None:
        cfg = AppConfig(
            fritzbox_host="198.51.100.10",
            fritz_username="admin-user",
            fritz_password="your-secret-password-here",
            debug_logging=True,
        )
        report = collect_diagnostics_report(cfg, qt_version="6.8.0", max_log_lines=20)

        self.assertIn("TrafficBox v", report)
        self.assertIn("Custom-Host=True", report)
        self.assertIn("Debug-Log=True", report)
        self.assertNotIn("198.51.100.10", report)
        self.assertNotIn("admin-user", report)
        self.assertNotIn("your-secret-password-here", report)

    def test_build_github_issue_url_truncates_long_reports(self) -> None:
        base = "https://github.com/WhiteSephi/traffic-box/issues"
        short_url, short_trunc = build_github_issue_url("hello world", base)
        self.assertFalse(short_trunc)
        self.assertTrue(short_url.startswith(base + "/new?"))

        long_body = "x" * (MAX_ISSUE_BODY_CHARS + 500)
        long_url, long_trunc = build_github_issue_url(long_body, base)
        self.assertTrue(long_trunc)
        self.assertTrue(long_url.startswith(base + "/new?"))
        self.assertIn("Zwischenablage", long_url)


if __name__ == "__main__":
    unittest.main()
