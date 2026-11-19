"""Network health diagnostics: Ping, Jitter, and active OS DNS latency monitoring."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
import re
import secrets
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
from typing import Tuple

from src.config import is_valid_host

_SHUTTING_DOWN: bool = False
_SSL_CONTEXT: ssl.SSLContext | None = None
_SSL_CONTEXT_LOCK = threading.Lock()


def _get_default_ssl_context() -> ssl.SSLContext:
    """Return a cached SSLContext loaded with OS trust roots."""
    global _SSL_CONTEXT
    with _SSL_CONTEXT_LOCK:
        if _SSL_CONTEXT is None:
            _SSL_CONTEXT = ssl.create_default_context()
        return _SSL_CONTEXT


@dataclass(frozen=True)
class DnsQueryResult:
    """Structured result of a direct RFC 1035 UDP DNS query."""

    ok: bool
    latency_ms: float | None = None
    rcode: int | None = None
    answers: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class HttpsCanaryResult:
    """Structured result of a single fresh-connection HTTPS canary check."""

    ok: bool
    latency_ms: float | None = None
    status_code: int | None = None
    error: str = ""

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _IP_OPTION_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("Ttl", ctypes.c_ubyte),
            ("Tos", ctypes.c_ubyte),
            ("Flags", ctypes.c_ubyte),
            ("OptionsSize", ctypes.c_ubyte),
            ("OptionsData", ctypes.c_void_p),
        ]

    class _ICMP_ECHO_REPLY(ctypes.Structure):
        _fields_ = [
            ("Address", wintypes.DWORD),
            ("Status", wintypes.ULONG),
            ("RoundTripTime", wintypes.ULONG),
            ("DataSize", wintypes.USHORT),
            ("Reserved", wintypes.USHORT),
            ("Data", ctypes.c_void_p),
            ("Options", _IP_OPTION_INFORMATION),
        ]

    class _IP_ADDR_STRING(ctypes.Structure):
        pass

    _IP_ADDR_STRING._fields_ = [
        ("Next", ctypes.POINTER(_IP_ADDR_STRING)),
        ("IpAddress", ctypes.c_char * 16),
        ("IpMask", ctypes.c_char * 16),
        ("Context", wintypes.DWORD),
    ]

    class _FIXED_INFO(ctypes.Structure):
        _fields_ = [
            ("HostName", ctypes.c_char * 132),
            ("DomainName", ctypes.c_char * 132),
            ("CurrentDnsServer", ctypes.POINTER(_IP_ADDR_STRING)),
            ("DnsServerList", _IP_ADDR_STRING),
            ("NodeType", wintypes.UINT),
            ("ScopeId", ctypes.c_char * 260),
            ("EnableRouting", wintypes.UINT),
            ("EnableProxy", wintypes.UINT),
            ("EnableDns", wintypes.UINT),
        ]


def set_shutting_down(shutting_down: bool = True) -> None:
    """Signal that the OS session or application is shutting down."""
    global _SHUTTING_DOWN
    _SHUTTING_DOWN = shutting_down


def _detect_windows_dns_iphlpapi() -> str:
    """Fallback in-process DNS server detection on Windows via iphlpapi.GetNetworkParams."""
    if sys.platform != "win32":
        return ""
    try:
        iphlpapi = ctypes.windll.iphlpapi
        iphlpapi.GetNetworkParams.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG)]
        iphlpapi.GetNetworkParams.restype = wintypes.DWORD
        size = wintypes.ULONG(ctypes.sizeof(_FIXED_INFO))
        buf = ctypes.create_string_buffer(size.value)
        ret = iphlpapi.GetNetworkParams(buf, ctypes.byref(size))
        if ret == 111:  # ERROR_BUFFER_OVERFLOW
            buf = ctypes.create_string_buffer(size.value)
            ret = iphlpapi.GetNetworkParams(buf, ctypes.byref(size))
        if ret == 0:
            info = ctypes.cast(buf, ctypes.POINTER(_FIXED_INFO)).contents
            dns_ip = info.DnsServerList.IpAddress.decode("ascii", errors="ignore").strip()
            if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", dns_ip):
                if not dns_ip.startswith("0.") and not dns_ip.startswith("127."):
                    return dns_ip
    except Exception:
        pass
    return ""


def detect_active_os_dns() -> str:
    """Detect the primary active DNS server IP configured on the host OS."""
    if _SHUTTING_DOWN:
        return ""

    if sys.platform == "win32":
        # Prefer active system DNS from Win32 iphlpapi before enumerating registry interfaces
        active_ip = _detect_windows_dns_iphlpapi()
        if active_ip:
            return active_ip

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

        return ""

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

        # 2. Try resolvectl dns (for NetworkManager / systemd-resolved active link) if not shutting down
        if not _SHUTTING_DOWN:
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


def _skip_dns_name(packet: bytes, offset: int) -> int:
    """Advance offset past a DNS QNAME/RRNAME (supports compression pointers), or -1 on error."""
    pkt_len = len(packet)
    steps = 0
    while offset < pkt_len and steps < 128:
        steps += 1
        length = packet[offset]
        if length == 0:
            return offset + 1
        tag_type = length & 0xC0
        if tag_type == 0xC0:
            return offset + 2 if (offset + 1) < pkt_len else -1
        if tag_type != 0:
            return -1
        next_off = offset + 1 + length
        if next_off > pkt_len:
            return -1
        offset = next_off
    return -1


def _parse_dns_response(reply: bytes, expected_tx_id: bytes) -> tuple[bool, int | None, tuple[str, ...]]:
    """Validate DNS UDP reply header and extract RCODE plus IPv4 A record answers."""
    if len(reply) < 12 or reply[:2] != expected_tx_id:
        return False, None, ()

    flags, qdcount, ancount = struct.unpack("!HHH", reply[2:8])
    if ((flags >> 15) & 1) != 1:  # QR must be 1 (response)
        return False, None, ()

    rcode = flags & 0x0F
    if rcode != 0 or ancount == 0:
        return True, rcode, ()

    offset = 12
    for _ in range(min(qdcount, 16)):
        offset = _skip_dns_name(reply, offset)
        if offset < 0 or (offset + 4) > len(reply):
            return True, rcode, ()
        offset += 4  # QTYPE + QCLASS

    answers: list[str] = []
    for _ in range(min(ancount, 32)):
        offset = _skip_dns_name(reply, offset)
        if offset < 0 or (offset + 10) > len(reply):
            break
        rtype, rclass, _ttl, rdlength = struct.unpack("!HHIH", reply[offset : offset + 10])
        offset += 10
        if (offset + rdlength) > len(reply):
            break
        if rtype == 1 and rclass == 1 and rdlength == 4:
            answers.append(socket.inet_ntoa(reply[offset : offset + 4]))
        offset += rdlength

    return True, rcode, tuple(answers)


def measure_dns_query(
    dns_server: str,
    domain: str = "cloudflare.com",
    timeout_sec: float = 1.5,
    accept_nxdomain: bool = False,
    reject_private_answers: bool = False,
) -> DnsQueryResult:
    """Execute a direct RFC 1035 UDP DNS query and validate RCODE and answer records."""
    if not dns_server or not domain or _SHUTTING_DOWN:
        return DnsQueryResult(ok=False, error="invalid_target")

    clean_domain = domain.strip().strip(".")
    if not clean_domain or len(clean_domain) > 253:
        return DnsQueryResult(ok=False, error="invalid_target")

    qname = b""
    for label in clean_domain.split("."):
        encoded = label.encode("ascii", errors="strict") if label.isascii() else label.encode("idna")
        if not encoded or len(encoded) > 63:
            return DnsQueryResult(ok=False, error="invalid_target")
        qname += bytes([len(encoded)]) + encoded
    qname += b"\x00"

    tx_id = os.urandom(2)
    header = tx_id + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    packet = header + qname + b"\x00\x01\x00\x01"

    family = socket.AF_INET6 if ":" in dns_server else socket.AF_INET
    sock = None
    try:
        sock = socket.socket(family, socket.SOCK_DGRAM)
        sock.settimeout(timeout_sec)
        t0 = time.perf_counter()
        sock.sendto(packet, (dns_server, 53))
        reply, addr = sock.recvfrom(1024)
        elapsed_ms = max(0.1, round((time.perf_counter() - t0) * 1000.0, 2))
        if addr[0].split("%")[0] != dns_server.split("%")[0]:
            return DnsQueryResult(ok=False, latency_ms=elapsed_ms, error="invalid_reply")

        valid, rcode, answers = _parse_dns_response(reply, tx_id)
        if not valid or rcode is None:
            return DnsQueryResult(ok=False, latency_ms=elapsed_ms, error="invalid_reply")

        if rcode == 0:
            if reject_private_answers and answers:
                for ip_str in answers:
                    try:
                        if not ipaddress.IPv4Address(ip_str).is_global:
                            return DnsQueryResult(
                                ok=False,
                                latency_ms=elapsed_ms,
                                rcode=rcode,
                                answers=answers,
                                error="hijacked",
                            )
                    except ipaddress.AddressValueError:
                        return DnsQueryResult(
                            ok=False,
                            latency_ms=elapsed_ms,
                            rcode=rcode,
                            answers=answers,
                            error="hijacked",
                        )
            return DnsQueryResult(ok=True, latency_ms=elapsed_ms, rcode=rcode, answers=answers)

        if rcode == 3:
            return DnsQueryResult(
                ok=accept_nxdomain,
                latency_ms=elapsed_ms,
                rcode=rcode,
                answers=answers,
                error="" if accept_nxdomain else "nxdomain",
            )

        rcode_err = {1: "formerr", 2: "servfail", 5: "refused"}.get(rcode, f"rcode_{rcode}")
        return DnsQueryResult(
            ok=False,
            latency_ms=elapsed_ms,
            rcode=rcode,
            answers=answers,
            error=rcode_err,
        )
    except (TimeoutError, socket.timeout):
        return DnsQueryResult(ok=False, error="timeout")
    except Exception:
        return DnsQueryResult(ok=False, error="socket_error")
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def measure_uncached_dns(
    dns_server: str,
    base_domain: str = "tbcheck.cloudflare.com",
    timeout_sec: float = 1.8,
) -> DnsQueryResult:
    """Query a unique nonce subdomain to bypass local AdGuard / optimistic DNS caches."""
    nonce = secrets.token_hex(3)
    domain = f"tb-{nonce}.{base_domain}"
    return measure_dns_query(
        dns_server,
        domain=domain,
        timeout_sec=timeout_sec,
        accept_nxdomain=True,
        reject_private_answers=True,
    )


def measure_dns_latency(dns_server: str, domain: str = "cloudflare.com", timeout_sec: float = 0.8) -> float | None:
    """Measure round-trip time to DNS server via minimal RFC 1035 UDP query."""
    res = measure_dns_query(
        dns_server,
        domain=domain,
        timeout_sec=timeout_sec,
        accept_nxdomain=False,
        reject_private_answers=False,
    )
    return res.latency_ms if res.ok else None


def has_global_ipv6() -> bool:
    """Check packet-free whether the host has a globally routable IPv6 address."""
    if _SHUTTING_DOWN:
        return False
    sock = None
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        sock.connect(("2606:4700:4700::1111", 443))
        local_ip = sock.getsockname()[0].split("%")[0]
        return ipaddress.IPv6Address(local_ip).is_global
    except (OSError, ValueError):
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def measure_https_canary(
    connect_ip: str,
    server_hostname: str,
    path: str = "/generate_204",
    family: int = socket.AF_INET,
    expected_statuses: tuple[int, ...] = (204,),
    timeout_sec: float = 2.0,
) -> HttpsCanaryResult:
    """Run a fresh non-keepalive HTTPS GET canary probe against a specific IPv4/IPv6 endpoint."""
    if not connect_ip or not server_hostname or _SHUTTING_DOWN:
        return HttpsCanaryResult(ok=False, error="invalid_target")

    req_path = path if path.startswith("/") else f"/{path}"
    raw_sock = None
    tls_sock = None
    try:
        raw_sock = socket.socket(family, socket.SOCK_STREAM)
        raw_sock.settimeout(timeout_sec)
        t0 = time.perf_counter()
        raw_sock.connect((connect_ip, 443))
        ctx = _get_default_ssl_context()
        tls_sock = ctx.wrap_socket(raw_sock, server_hostname=server_hostname)
        raw_sock = None  # Owned by tls_sock now

        request_bytes = (
            f"GET {req_path} HTTP/1.1\r\n"
            f"Host: {server_hostname}\r\n"
            "User-Agent: TrafficBox\r\n"
            "Connection: close\r\n"
            "Cache-Control: no-cache\r\n"
            "\r\n"
        ).encode("ascii")
        tls_sock.sendall(request_bytes)

        buf = b""
        while b"\n" not in buf and len(buf) < 2048:
            chunk = tls_sock.recv(1024)
            if not chunk:
                break
            buf += chunk

        elapsed_ms = max(0.1, round((time.perf_counter() - t0) * 1000.0, 2))
        first_line = buf.split(b"\n", 1)[0].strip()
        match = re.match(rb"^HTTP/\d\.\d\s+(\d{3})", first_line)
        if not match:
            return HttpsCanaryResult(ok=False, latency_ms=elapsed_ms, error="bad_status")

        status_code = int(match.group(1))
        if status_code in expected_statuses:
            return HttpsCanaryResult(ok=True, latency_ms=elapsed_ms, status_code=status_code)
        if 300 <= status_code < 400:
            return HttpsCanaryResult(
                ok=False,
                latency_ms=elapsed_ms,
                status_code=status_code,
                error="captive_portal",
            )
        return HttpsCanaryResult(
            ok=False,
            latency_ms=elapsed_ms,
            status_code=status_code,
            error=f"http_{status_code}",
        )
    except ssl.SSLError:
        return HttpsCanaryResult(ok=False, error="tls_error")
    except (TimeoutError, socket.timeout):
        return HttpsCanaryResult(ok=False, error="timeout")
    except OSError:
        return HttpsCanaryResult(ok=False, error="connect_error")
    finally:
        if tls_sock is not None:
            try:
                tls_sock.close()
            except OSError:
                pass
        if raw_sock is not None:
            try:
                raw_sock.close()
            except OSError:
                pass


def parse_ping_output(out_text: str) -> float | None:
    """Extract round-trip ping latency in milliseconds from CLI ping output."""
    match = re.search(r"(?:Zeit|time)[=<]\s*(\d+(?:\.\d+)?)\s*ms", out_text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _measure_ping_windows_icmp(target_host: str, timeout_ms: int = 800) -> float | None:
    """Measure ICMP Echo round-trip time in-process via Windows iphlpapi.dll (no ping.exe subprocess)."""
    if sys.platform != "win32" or _SHUTTING_DOWN:
        return None
    try:
        target_ip = socket.gethostbyname(target_host)
        dest_addr = struct.unpack("<I", socket.inet_aton(target_ip))[0]

        iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
        iphlpapi.IcmpCreateFile.argtypes = []
        iphlpapi.IcmpCreateFile.restype = wintypes.HANDLE
        iphlpapi.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
        iphlpapi.IcmpCloseHandle.restype = wintypes.BOOL
        iphlpapi.IcmpSendEcho.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.WORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        iphlpapi.IcmpSendEcho.restype = wintypes.DWORD

        handle = iphlpapi.IcmpCreateFile()
        invalid_handle = ctypes.c_void_p(-1).value
        if not handle or handle == invalid_handle:
            return None

        try:
            payload = b"TrafficBoxPing16"
            reply_size = ctypes.sizeof(_ICMP_ECHO_REPLY) + len(payload) + 16
            reply_buf = ctypes.create_string_buffer(reply_size)

            t0 = time.perf_counter()
            res = iphlpapi.IcmpSendEcho(
                wintypes.HANDLE(handle),
                wintypes.DWORD(dest_addr),
                payload,
                len(payload),
                None,
                reply_buf,
                reply_size,
                max(100, int(timeout_ms)),
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if res > 0:
                reply = ctypes.cast(reply_buf, ctypes.POINTER(_ICMP_ECHO_REPLY)).contents
                if reply.Status == 0:  # IP_SUCCESS
                    return max(0.1, round(elapsed_ms, 2))
        finally:
            iphlpapi.IcmpCloseHandle(wintypes.HANDLE(handle))
    except Exception:
        pass
    return None


def _measure_ping_linux_icmp(target_host: str, timeout_ms: int = 800) -> float | None:
    """Measure ICMP Echo round-trip time in-process via Linux unprivileged SOCK_DGRAM ICMP socket."""
    if sys.platform == "win32" or _SHUTTING_DOWN:
        return None
    sock = None
    try:
        target_ip = socket.gethostbyname(target_host)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
        sock.settimeout(max(0.2, timeout_ms / 1000.0))
        # ICMP Echo Request: Type=8, Code=0, Checksum=0 (calculated by kernel), ID=0, Seq=1
        packet = struct.pack("!BBHHH", 8, 0, 0, 0, 1) + b"TrafficBoxPing16"
        t0 = time.perf_counter()
        sock.sendto(packet, (target_ip, 0))
        reply, _ = sock.recvfrom(1024)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if len(reply) >= 8 and reply[0] == 0:  # ICMP_ECHOREPLY (Type 0)
            return max(0.1, round(elapsed_ms, 2))
    except Exception:
        pass
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
    return None


def _measure_ping_tcp_fallback(target_host: str, timeout_ms: int = 800) -> float | None:
    """Measure TCP handshake latency on port 443 (HTTPS) or 53 (DNS) as fallback."""
    if _SHUTTING_DOWN:
        return None
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


def measure_ping(target_host: str, timeout_ms: int = 800) -> float | None:
    """Measure round-trip ping time to target host (in-process ICMP or TCP fallback)."""
    if not is_valid_host(target_host) or _SHUTTING_DOWN:
        return None

    if sys.platform == "win32":
        # Windows: Native in-process Win32 IcmpSendEcho API (never spawns ping.exe, preventing 0xc0000142 on shutdown)
        icmp_ms = _measure_ping_windows_icmp(target_host, timeout_ms=timeout_ms)
        if icmp_ms is not None:
            return icmp_ms
        return _measure_ping_tcp_fallback(target_host, timeout_ms=timeout_ms)

    # Linux / Unix:
    # 1. Try unprivileged in-process ICMP datagram socket (no subprocess fork)
    icmp_ms = _measure_ping_linux_icmp(target_host, timeout_ms=timeout_ms)
    if icmp_ms is not None:
        return icmp_ms

    # 2. Fallback to system ping binary only if kernel restricts SOCK_DGRAM ICMP and not shutting down
    if not _SHUTTING_DOWN:
        try:
            timeout_sec = max(1, timeout_ms // 1000)
            cmd = ["ping", "-c", "1", "-W", str(timeout_sec), "--", target_host]
            t0 = time.perf_counter()
            res = subprocess.run(
                cmd,
                capture_output=True,
                timeout=max(1.5, timeout_ms / 1000.0 + 0.5),
            )
            if res.returncode == 0:
                out_text = res.stdout.decode("utf-8", errors="replace")
                parsed = parse_ping_output(out_text)
                if parsed is not None:
                    return parsed
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                return round(elapsed_ms, 2)
        except Exception:
            pass

    # 3. TCP connect fallback on port 443 (HTTPS) or 53 (DNS)
    return _measure_ping_tcp_fallback(target_host, timeout_ms=timeout_ms)


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
