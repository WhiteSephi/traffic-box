"""Formatting helpers for transfer rates, byte volumes, and durations."""

from __future__ import annotations


def format_rate(bytes_per_sec: float, show_as_bits: bool = False) -> str:
    """Format bytes/sec into a German-formatted rate string (e.g., kB/s, MB/s, kbit/s, Mbit/s)."""
    val = max(0.0, bytes_per_sec)
    if show_as_bits:
        bits = val * 8.0
        if bits >= 1_000_000:
            formatted = f"{bits / 1_000_000:.2f} Mbit/s"
        elif bits >= 1_000:
            formatted = f"{bits / 1_000:.1f} kbit/s"
        else:
            formatted = f"{bits:.0f} bit/s"
    else:
        if val >= 1024 * 1024:
            formatted = f"{val / (1024 * 1024):.2f} MB/s"
        elif val >= 1024:
            formatted = f"{val / 1024:.2f} kB/s"
        else:
            formatted = f"{val:.0f} B/s"
    return formatted.replace(".", ",")


def format_bytes(num_bytes: int | float, use_decimal: bool = True) -> str:
    """Format cumulative byte count into KB, MB, GB, or TB with comma decimal separator.

    If use_decimal is True (default, matching Fritz!OS SI standard), uses divisor 1000.
    If use_decimal is False, uses binary divisor 1024.
    """
    val = max(0.0, float(num_bytes))
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    divisor = 1000.0 if use_decimal else 1024.0
    while val >= divisor and idx < len(units) - 1:
        val /= divisor
        idx += 1
    if idx == 0:
        return f"{int(val)} B"
    return f"{val:.2f} {units[idx]}".replace(".", ",")


def format_uptime(seconds: int) -> str:
    """Format uptime in seconds into human-readable days, hours, and minutes."""
    if seconds <= 0:
        return "-"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    return f"{hours:02d}h {minutes:02d}m"
