"""Cross-platform local network interface traffic monitor (Linux & Windows).

Measures instantaneous bytes sent and received by the local machine's active
network adapter(s) using only the Python standard library.
"""

from __future__ import annotations

import sys
import time

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _MIB_IF_ROW2(ctypes.Structure):
        _fields_ = [
            ("InterfaceLuid", ctypes.c_uint64),
            ("InterfaceIndex", wintypes.DWORD),
            ("InterfaceGuid", ctypes.c_byte * 16),
            ("Alias", wintypes.WCHAR * 257),
            ("Description", wintypes.WCHAR * 257),
            ("PhysicalAddressLength", wintypes.ULONG),
            ("PhysicalAddress", ctypes.c_byte * 32),
            ("PermanentPhysicalAddress", ctypes.c_byte * 32),
            ("Mtu", wintypes.ULONG),
            ("Type", wintypes.DWORD),
            ("TunnelType", ctypes.c_int),
            ("MediaType", ctypes.c_int),
            ("PhysicalMediumType", ctypes.c_int),
            ("AccessType", ctypes.c_int),
            ("DirectionType", ctypes.c_int),
            ("InterfaceAndOperStatusFlags", ctypes.c_byte),
            ("OperStatus", ctypes.c_int),
            ("AdminStatus", ctypes.c_int),
            ("MediaConnectState", ctypes.c_int),
            ("NetworkGuid", ctypes.c_byte * 16),
            ("ConnectionType", ctypes.c_int),
            ("TransmitLinkSpeed", ctypes.c_uint64),
            ("ReceiveLinkSpeed", ctypes.c_uint64),
            ("InOctets", ctypes.c_uint64),
            ("InUcastPkts", ctypes.c_uint64),
            ("InNUcastPkts", ctypes.c_uint64),
            ("InDiscards", ctypes.c_uint64),
            ("InErrors", ctypes.c_uint64),
            ("InUnknownProtos", ctypes.c_uint64),
            ("InUcastOctets", ctypes.c_uint64),
            ("InMulticastOctets", ctypes.c_uint64),
            ("InBroadcastOctets", ctypes.c_uint64),
            ("OutOctets", ctypes.c_uint64),
            ("OutUcastPkts", ctypes.c_uint64),
            ("OutNUcastPkts", ctypes.c_uint64),
            ("OutDiscards", ctypes.c_uint64),
            ("OutErrors", ctypes.c_uint64),
            ("OutUcastOctets", ctypes.c_uint64),
            ("OutMulticastOctets", ctypes.c_uint64),
            ("OutBroadcastOctets", ctypes.c_uint64),
            ("OutQLen", ctypes.c_uint64),
        ]

    class _MIB_IF_TABLE2(ctypes.Structure):
        _fields_ = [
            ("NumEntries", wintypes.ULONG),
            ("Table", _MIB_IF_ROW2 * 1),
        ]


def _read_windows_adapter_bytes() -> tuple[int, int, bool]:
    """Read cumulative in/out octets from active non-loopback network adapters on Windows."""
    try:
        iphlpapi = ctypes.windll.iphlpapi
        iphlpapi.GetIfTable2.argtypes = [ctypes.POINTER(ctypes.POINTER(_MIB_IF_TABLE2))]
        iphlpapi.GetIfTable2.restype = wintypes.ULONG
        iphlpapi.FreeMibTable.argtypes = [ctypes.c_void_p]
        iphlpapi.FreeMibTable.restype = None
        p_table = ctypes.POINTER(_MIB_IF_TABLE2)()
        ret = iphlpapi.GetIfTable2(ctypes.byref(p_table))
        if ret != 0 or not p_table:
            return 0, 0, False

        try:
            table = p_table.contents
            row_array = ctypes.cast(ctypes.byref(table.Table), ctypes.POINTER(_MIB_IF_ROW2))
            total_in = 0
            total_out = 0
            found_active = False

            for i in range(table.NumEntries):
                row = row_array[i]
                # OperStatus == 1 is IfOperStatusUp; Type 24 is IF_TYPE_SOFTWARE_LOOPBACK
                if row.OperStatus == 1 and row.Type != 24:
                    total_in += row.InOctets
                    total_out += row.OutOctets
                    found_active = True

            return total_in, total_out, found_active
        finally:
            iphlpapi.FreeMibTable(p_table)
    except Exception:
        return 0, 0, False


def _read_linux_adapter_bytes() -> tuple[int, int, bool]:
    """Read cumulative received/transmitted bytes from /proc/net/dev on Linux."""
    try:
        total_in = 0
        total_out = 0
        found_active = False
        with open("/proc/net/dev", "r", encoding="utf-8") as f:
            for line in f:
                if ":" not in line:
                    continue
                iface, data = line.split(":", 1)
                iface = iface.strip()
                # Skip loopback and virtual virtualization interfaces
                if iface == "lo" or iface.startswith(("veth", "docker", "virbr", "br-")):
                    continue
                fields = data.split()
                if len(fields) >= 9:
                    rx_bytes = int(fields[0])
                    tx_bytes = int(fields[8])
                    total_in += rx_bytes
                    total_out += tx_bytes
                    found_active = True
        return total_in, total_out, found_active
    except Exception:
        return 0, 0, False


class LocalTrafficMonitor:
    """Calculates instantaneous transfer rates for the local machine in bytes/sec."""

    def __init__(self) -> None:
        self._last_time: float | None = None
        self._last_in_bytes: int = 0
        self._last_out_bytes: int = 0
        self._initialized: bool = False
        self._session_rx: int = 0
        self._session_tx: int = 0

    @property
    def session_bytes_received(self) -> int:
        """Return cumulative received bytes since widget start or last reset."""
        return self._session_rx

    @property
    def session_bytes_sent(self) -> int:
        """Return cumulative sent bytes since widget start or last reset."""
        return self._session_tx

    def reset_session_counters(self) -> None:
        """Reset cumulative local session byte counters to zero."""
        self._session_rx = 0
        self._session_tx = 0

    def fetch_rates_bps(self) -> tuple[float, float, bool]:
        """Return (download_bps, upload_bps, is_success)."""
        if sys.platform == "win32":
            in_bytes, out_bytes, ok = _read_windows_adapter_bytes()
        else:
            in_bytes, out_bytes, ok = _read_linux_adapter_bytes()

        if not ok:
            return 0.0, 0.0, False

        now = time.monotonic()
        if not self._initialized or self._last_time is None:
            self._last_time = now
            self._last_in_bytes = in_bytes
            self._last_out_bytes = out_bytes
            self._initialized = True
            return 0.0, 0.0, True

        dt = max(0.1, now - self._last_time)
        delta_in = in_bytes - self._last_in_bytes
        delta_out = out_bytes - self._last_out_bytes

        self._last_time = now
        self._last_in_bytes = in_bytes
        self._last_out_bytes = out_bytes

        # Guard against adapter reset or wrap-around
        if delta_in < 0 or delta_out < 0:
            return 0.0, 0.0, True

        self._session_rx += delta_in
        self._session_tx += delta_out

        down_bps = float(delta_in) / dt
        up_bps = float(delta_out) / dt
        return down_bps, up_bps, True
