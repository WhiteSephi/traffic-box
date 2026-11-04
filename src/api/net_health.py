"""Network health diagnostics: Ping, Jitter, and active OS DNS latency monitoring."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from typing import Tuple


def detect_active_os_dns() -> str:
    """Detect the primary active DNS server IP configured on the host OS."""
    if sys.platform == "win32":
        try:
            import winreg

            key_path = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as root_key:
                num_subkeys = winreg.QueryInfoKey(root_key)[0]
                for i in range(num_subkeys):
                    subkey_name = winreg.EnumKey(root_key, i)
                    try:
                        with winreg.OpenKey(root_key, subkey_name) as subkey:
                            for val_name in ("NameServer", "DhcpNameServer"):
                                try:
                                    val, _ = winreg.QueryValueEx(subkey, val_name)
                                    if val:
                                        parts = re.split(r"[, ]+", str(val).strip())
                                        for part in parts:
                                            # Validate basic IPv4 format
                                            if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", part):
                                                if not part.startswith("0.") and not part.startswith("127."):
                                                    return part
                                except FileNotFoundError:
                                    pass
                    except OSError:
                        pass
        except Exception:
            pass

        # Fallback to ipconfig if registry query didn't return an IP
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            res = subprocess.run(
                ["ipconfig", "/all"],
                capture_output=True,
                text=True,
                timeout=2.0,
                creationflags=flags,
            )
            ips = re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", res.stdout)
            # Find IP after "DNS-Server" or "DNS Servers"
            match = re.search(r"DNS[^\r\n:]*:\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", res.stdout)
            if match:
                return match.group(1)
        except Exception:
            pass

    else:
        # Linux / Unix: check systemd-resolved uplink resolv.conf first, then resolvectl, then /etc/resolv.conf
        # 1. /run/systemd/resolve/resolv.conf (contains real upstream uplink DNS servers, bypassing 127.0.0.53 stub)
        for p in ("/run/systemd/resolve/resolv.conf", "/etc/resolv.conf"):
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("nameserver"):
                                parts = line.split()
                                if len(parts) >= 2 and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", parts[1]):
                                    ip = parts[1]
                                    if not ip.startswith("127.") and not ip.startswith("0."):
                                        return ip
                except Exception:
                    pass

        # 2. Try resolvectl dns (for NetworkManager / systemd-resolved active link)
        try:
            res = subprocess.run(
                ["resolvectl", "dns"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            if res.returncode == 0:
                for match in re.finditer(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", res.stdout):
                    ip = match.group(0)
                    if not ip.startswith("127.") and not ip.startswith("0."):
                        return ip
        except Exception:
            pass

        # 3. Fallback: if only loopback was found in /etc/resolv.conf, return it
        resolv_path = "/etc/resolv.conf"
        if os.path.isfile(resolv_path):
            try:
                with open(resolv_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("nameserver"):
                            parts = line.split()
                            if len(parts) >= 2 and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", parts[1]):
                                return parts[1]
            except Exception:
                pass

    return ""


def measure_dns_latency(dns_server: str, domain: str = "cloudflare.com", timeout_sec: float = 0.8) -> float | None:
    """Measure round-trip time to DNS server via minimal RFC 1035 UDP query."""
    if not dns_server:
        return None
    try:
        # Build minimal standard DNS query for A record
        # Header: ID=0xbeef, flags=0x0100 (standard query, recursion desired), QDCOUNT=1, ANCOUNT=0, NSCOUNT=0, ARCOUNT=0
        header = b"\xbe\xef\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
        qname = b""
        for label in domain.split("."):
            encoded = label.encode("latin1")
            qname += bytes([len(encoded)]) + encoded
        qname += b"\x00"  # End of domain name
        # QTYPE=1 (A), QCLASS=1 (IN)
        question = qname + b"\x00\x01\x00\x01"
        packet = header + question

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout_sec)
        t0 = time.perf_counter()
        try:
            sock.sendto(packet, (dns_server, 53))
            _reply, _ = sock.recvfrom(512)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return max(0.1, round(elapsed_ms, 2))
        finally:
            sock.close()
    except Exception:
        return None


def measure_ping(target_host: str, timeout_ms: int = 800) -> float | None:
    """Measure round-trip ping time to target host (ICMP or TCP fallback)."""
    if not target_host:
        return None

    # First attempt: System ICMP ping command
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if sys.platform == "win32":
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), target_host]
        else:
            timeout_sec = max(1, timeout_ms // 1000)
            cmd = ["ping", "-c", "1", "-W", str(timeout_sec), target_host]

        t0 = time.perf_counter()
        res = subprocess.run(
            cmd,
            capture_output=True,
            timeout=max(1.5, timeout_ms / 1000.0 + 0.5),
            creationflags=flags,
        )
        if res.returncode == 0:
            encoding = "cp850" if sys.platform == "win32" else "utf-8"
            out_text = res.stdout.decode(encoding, errors="replace")
            # Parse time from stdout
            # Windows: "Zeit=14ms", "Zeit<1ms", "time=14ms", "time<1ms"
            # Linux: "time=14.2 ms"
            match = re.search(r"(?:Zeit|time)[=<]\s*(\d+(?:\.\d+)?)\s*ms", out_text, re.IGNORECASE)
            if match:
                return float(match.group(1))
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return round(elapsed_ms, 2)
    except Exception:
        pass

    # Second attempt: TCP connect fallback on port 443 (HTTPS) or 53 (DNS)
    for port in (443, 53):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_ms / 1000.0)
            t0 = time.perf_counter()
            sock.connect((target_host, port))
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return round(elapsed_ms, 2)
        except Exception:
            continue
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    return None


class NetworkHealthMonitor:
    """Thread-safe background helper to track Ping, Jitter, and DNS latency."""

    def __init__(self, endpoint: str = "1.1.1.1") -> None:
        self.endpoint = endpoint
        self._last_ping: float | None = None
        self._last_jitter: float = 0.0
        self._cached_dns_ip: str = ""
        self._last_dns_check_time: float = 0.0

    def set_endpoint(self, endpoint: str) -> None:
        self.endpoint = endpoint.strip() or "1.1.1.1"

    def tick(self, check_ping: bool = True, check_dns: bool = True) -> Tuple[float | None, float, str, float | None]:
        """Perform one diagnostic check tick. Returns (ping_ms, jitter_ms, dns_ip, dns_ms)."""
        ping_val: float | None = None
        jitter_val: float = self._last_jitter

        if check_ping:
            ping_val = measure_ping(self.endpoint)
            if ping_val is not None:
                if self._last_ping is not None:
                    # Instantaneous jitter = absolute diff between successive pings
                    diff = abs(ping_val - self._last_ping)
                    # Smooth with rolling EMA (weight 0.4 for live responsiveness)
                    jitter_val = round(self._last_jitter * 0.6 + diff * 0.4, 2)
                else:
                    jitter_val = 0.0
                self._last_ping = ping_val
                self._last_jitter = jitter_val
            else:
                self._last_ping = None

        dns_ip = self._cached_dns_ip
        dns_ms: float | None = None

        if check_dns:
            now = time.monotonic()
            # Refresh active DNS IP detection every 30 seconds
            if not self._cached_dns_ip or (now - self._last_dns_check_time) > 30.0:
                detected = detect_active_os_dns()
                if detected:
                    self._cached_dns_ip = detected
                    dns_ip = detected
                self._last_dns_check_time = now

            if dns_ip:
                dns_ms = measure_dns_latency(dns_ip)

        return ping_val, jitter_val, dns_ip, dns_ms
