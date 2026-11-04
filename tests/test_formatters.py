"""Unit tests for ui/formatters.py."""

from __future__ import annotations

import unittest

from src.ui.formatters import format_bytes, format_rate, format_uptime


class TestFormatters(unittest.TestCase):
    """Test rate, byte volume, and uptime formatting."""

    def test_format_rate_bytes_mode(self) -> None:
        """Verify format_rate with show_as_bits=False (default)."""
        self.assertEqual(format_rate(0), "0 B/s")
        self.assertEqual(format_rate(500), "500 B/s")
        self.assertEqual(format_rate(1024), "1,00 kB/s")
        self.assertEqual(format_rate(1536), "1,50 kB/s")
        self.assertEqual(format_rate(1024 * 1024), "1,00 MB/s")
        self.assertEqual(format_rate(10.5 * 1024 * 1024), "10,50 MB/s")

    def test_format_rate_bits_mode(self) -> None:
        """Verify format_rate with show_as_bits=True."""
        # 125,000 bytes/sec = 1,000,000 bits/sec = 1.00 Mbit/s
        self.assertEqual(format_rate(125_000, show_as_bits=True), "1,00 Mbit/s")
        # 125 bytes/sec = 1,000 bits/sec = 1.0 kbit/s
        self.assertEqual(format_rate(125, show_as_bits=True), "1,0 kbit/s")
        # 10 bytes/sec = 80 bit/s
        self.assertEqual(format_rate(10, show_as_bits=True), "80 bit/s")

    def test_format_bytes_decimal(self) -> None:
        """Verify format_bytes in decimal mode (Fritz!OS SI standard, divisor 1000)."""
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(500), "500 B")
        self.assertEqual(format_bytes(1_000), "1,00 KB")
        self.assertEqual(format_bytes(1_000_000), "1,00 MB")
        self.assertEqual(format_bytes(1_000_000_000), "1,00 GB")
        self.assertEqual(format_bytes(2_450_000_000), "2,45 GB")
        self.assertEqual(format_bytes(1_000_000_000_000), "1,00 TB")

    def test_format_bytes_binary(self) -> None:
        """Verify format_bytes in binary mode (divisor 1024)."""
        self.assertEqual(format_bytes(1024, use_decimal=False), "1,00 KB")
        self.assertEqual(format_bytes(1024 * 1024, use_decimal=False), "1,00 MB")
        self.assertEqual(format_bytes(1024 * 1024 * 1024, use_decimal=False), "1,00 GB")

    def test_format_uptime(self) -> None:
        """Verify format_uptime into human-readable strings."""
        self.assertEqual(format_uptime(0), "-")
        self.assertEqual(format_uptime(-10), "-")
        self.assertEqual(format_uptime(125), "00h 02m")
        self.assertEqual(format_uptime(3665), "01h 01m")
        self.assertEqual(format_uptime(86400), "1d 00h 00m")
        self.assertEqual(format_uptime(86400 * 3 + 3600 * 4 + 60 * 15), "3d 04h 15m")


if __name__ == "__main__":
    unittest.main()
