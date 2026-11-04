"""Main frameless floating Fritz!Box Traffic Widget."""

from __future__ import annotations

from PySide6.QtCore import (
    QObject,
    QPoint,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QContextMenuEvent,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizeGrip,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.api.fritz_monitor import FritzGuestMonitorClient
from src.api.models import OnlineCounterStats, PeriodCounter, TrafficSample
from src.api.upnp_client import FritzUpnpClient
from src.config import AppConfig
from src.ui.formatters import format_bytes, format_rate, format_uptime
from src.ui.graph_canvas import SplitTrafficGraphWidget
from src.ui.online_counter_view import OnlineCounterView
from src.ui.settings_dlg import SettingsDialog
from src.ui.tray import create_router_icon


class PollingWorker(QObject):
    """Background worker that polls Fritz!Box UPnP & optional Guest Monitor off the GUI thread."""

    sample_ready = Signal(object)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.upnp = FritzUpnpClient(
            host=self.config.fritzbox_host,
            port=self.config.upnp_port,
        )
        self.guest_client = FritzGuestMonitorClient(
            host=self.config.fritzbox_host,
            username=self.config.fritz_username,
            password=self.config.fritz_password,
        )
        self._cached_counters = OnlineCounterStats()
        self._counter_tick: int = 0
        self._busy = False

    @Slot()
    def poll_once(self) -> None:
        """Execute a single network poll and emit the resulting TrafficSample."""
        if self._busy:
            return
        self._busy = True
        try:
            self.upnp.update_target(self.config.fritzbox_host, self.config.upnp_port)
            sample = self.upnp.fetch_sample()

            if (
                sample.is_connected
                and self.config.enable_guest_monitor
                and self.config.fritz_password
            ):
                self.guest_client.update_credentials(
                    self.config.fritzbox_host,
                    self.config.fritz_username,
                    self.config.fritz_password,
                )
                g_down, g_up, g_ok = self.guest_client.fetch_guest_rates_bps()
                if g_ok:
                    sample.guest_download_bps = min(sample.download_bps, g_down)
                    sample.guest_upload_bps = min(sample.upload_bps, g_up)
                    sample.guest_active = True

                if self._counter_tick % 15 == 0 or not self._cached_counters.is_available:
                    fresh_counters = self.guest_client.fetch_online_counters()
                    if fresh_counters.is_available:
                        self._cached_counters = fresh_counters
                self._counter_tick += 1
                sample.online_counters = self._cached_counters
            else:
                self._counter_tick = 0
                self._cached_counters = OnlineCounterStats()

            self.sample_ready.emit(sample)
        finally:
            self._busy = False

    @Slot()
    def reset_session(self) -> None:
        """Reset cumulative session counters."""
        self.upnp.reset_session_counters()


class TrafficBox(QWidget):
    """Frameless, translucent cross-platform desktop widget for live Fritz!Box traffic."""

    request_poll = Signal()
    request_reset_session = Signal()

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self._drag_offset: QPoint | None = None
        self._peak_down_bps: float = 0.0
        self._peak_up_bps: float = 0.0
        self._last_sample: TrafficSample = TrafficSample()
        self._settings_dlg: SettingsDialog | None = None
        self._in_layout_transition: bool = False
        self._was_compact: bool = self.config.compact_mode
        self._was_counters: bool = self.config.active_view == "counters"

        self._configure_window_flags()
        self._build_ui()
        self._setup_tray_icon()
        self._apply_config_visuals()
        self._restore_geometry()
        self._setup_worker_thread()

    def _configure_window_flags(self) -> None:
        """Apply frameless, tool, and optional always-on-top window flags."""
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.config.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle(self.config.title)
        self.setWindowIcon(create_router_icon(True))

    def _build_ui(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(9, 7, 9, 7)
        self.main_layout.setSpacing(5)

        # --- 1. Header Bar (Icon + Title + View Switcher Pills) ---
        header_row = QHBoxLayout()
        header_row.setContentsMargins(2, 0, 2, 0)
        header_row.setSpacing(5)

        self.lbl_icon = QLabel()
        self.lbl_icon.setPixmap(create_router_icon(True).pixmap(QSize(18, 18)))
        self.lbl_title = QLabel(self.config.title)
        title_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        self.lbl_title.setFont(title_font)

        self.lbl_scale_badge = QLabel("√-Skala")
        badge_font = QFont("Segoe UI", 7)
        self.lbl_scale_badge.setFont(badge_font)

        self.btn_view_graph = QPushButton("📈 Graph")
        self.btn_view_graph.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_view_graph.setFixedHeight(20)
        self.btn_view_graph.clicked.connect(lambda: self._switch_active_view("graph"))

        self.btn_view_counters = QPushButton("📊 Zähler")
        self.btn_view_counters.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_view_counters.setFixedHeight(20)
        self.btn_view_counters.clicked.connect(lambda: self._switch_active_view("counters"))

        header_row.addWidget(self.lbl_icon)
        header_row.addWidget(self.lbl_title)
        header_row.addStretch(1)
        header_row.addWidget(self.lbl_scale_badge)
        header_row.addWidget(self.btn_view_graph)
        header_row.addWidget(self.btn_view_counters)
        self.main_layout.addLayout(header_row)

        # --- 2. Live Rate Readouts + Utilization % Bars (Down & Up) ---
        rates_row = QHBoxLayout()
        rates_row.setContentsMargins(2, 0, 2, 2)
        rates_row.setSpacing(10)

        # Download Column
        down_col = QVBoxLayout()
        down_col.setSpacing(2)
        self.lbl_down_header = QLabel("⬇ Down:")
        self.lbl_down_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_down_header.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))

        self.lbl_down_rate = QLabel("0,00 kB/s")
        self.lbl_down_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_down_rate.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))

        self.bar_down_util = QProgressBar()
        self.bar_down_util.setRange(0, 1000)
        self.bar_down_util.setValue(0)
        self.bar_down_util.setTextVisible(False)
        self.bar_down_util.setFixedHeight(5)

        self.lbl_down_meta = QLabel("0,0% • Peak: 0 B/s")
        self.lbl_down_meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_down_meta.setFont(QFont("Segoe UI", 7))

        self.lbl_guest_down = QLabel("")
        self.lbl_guest_down.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_guest_down.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        self.lbl_guest_down.setVisible(False)

        down_col.addWidget(self.lbl_down_header)
        down_col.addWidget(self.lbl_down_rate)
        down_col.addWidget(self.bar_down_util)
        down_col.addWidget(self.lbl_down_meta)
        down_col.addWidget(self.lbl_guest_down)

        # Upload Column
        up_col = QVBoxLayout()
        up_col.setSpacing(2)
        self.lbl_up_header = QLabel("⬆ Up:")
        self.lbl_up_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_up_header.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))

        self.lbl_up_rate = QLabel("0,00 kB/s")
        self.lbl_up_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_up_rate.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))

        self.bar_up_util = QProgressBar()
        self.bar_up_util.setRange(0, 1000)
        self.bar_up_util.setValue(0)
        self.bar_up_util.setTextVisible(False)
        self.bar_up_util.setFixedHeight(5)

        self.lbl_up_meta = QLabel("0,0% • Peak: 0 B/s")
        self.lbl_up_meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_up_meta.setFont(QFont("Segoe UI", 7))

        self.lbl_guest_up = QLabel("")
        self.lbl_guest_up.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_guest_up.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        self.lbl_guest_up.setVisible(False)

        up_col.addWidget(self.lbl_up_header)
        up_col.addWidget(self.lbl_up_rate)
        up_col.addWidget(self.bar_up_util)
        up_col.addWidget(self.lbl_up_meta)
        up_col.addWidget(self.lbl_guest_up)

        rates_row.addLayout(down_col, 1)
        rates_row.addLayout(up_col, 1)
        self.main_layout.addLayout(rates_row)

        # --- 3. Center Stacked Area (Split Graph vs. Online-Zähler Table) ---
        self.center_stack = QStackedWidget(self)
        self.graph_widget = SplitTrafficGraphWidget(self.config, self)
        self.counter_view = OnlineCounterView(
            self.config, on_open_settings=self.open_settings_dialog, parent=self
        )
        self.center_stack.addWidget(self.graph_widget)
        self.center_stack.addWidget(self.counter_view)
        self.main_layout.addWidget(self.center_stack, 1)

        # --- 4. Footer Row (Session Totals + Resize Grip) ---
        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(2, 0, 0, 0)
        footer_row.setSpacing(4)

        self.lbl_footer = QLabel("Σ Down: 0 B  •  Σ Up: 0 B")
        self.lbl_footer.setFont(QFont("Segoe UI", 7))

        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(12, 12)

        footer_row.addWidget(self.lbl_footer, 1)
        footer_row.addWidget(
            self.size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight
        )
        self.main_layout.addLayout(footer_row)

    def _setup_tray_icon(self) -> None:
        self.tray_icon = QSystemTrayIcon(create_router_icon(True), self)
        self.tray_icon.setToolTip("TrafficBox Widget")
        self.tray_icon.setContextMenu(self._build_context_menu())
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _setup_worker_thread(self) -> None:
        self._worker_thread = QThread(self)
        self._worker = PollingWorker(self.config)
        self._worker.moveToThread(self._worker_thread)

        self.request_poll.connect(self._worker.poll_once)
        self.request_reset_session.connect(self._worker.reset_session)
        self._worker.sample_ready.connect(self._on_sample_received)

        self._worker_thread.start()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.request_poll.emit)

        delay_ms = max(0, self.config.start_delay_sec * 1000)
        QTimer.singleShot(delay_ms, self._start_polling)

    def _start_polling(self) -> None:
        self.request_poll.emit()
        interval_ms = max(500, self.config.refresh_interval_sec * 1000)
        self._poll_timer.start(interval_ms)

    def _restore_geometry(self) -> None:
        w = max(210, self.config.widget_width)
        h = 95 if self.config.compact_mode else max(175, self.config.widget_height)
        self.resize(w, h)

        if self.config.pos_x >= 0 and self.config.pos_y >= 0:
            self.move(self.config.pos_x, self.config.pos_y)
        else:
            screen = QApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                self.move(avail.right() - w - 24, avail.bottom() - h - 24)

    def _apply_config_visuals(self) -> None:
        """Apply colors, fonts, compact mode, and window flags from AppConfig."""
        # Update window flags if AlwaysOnTop changed
        want_top = self.config.always_on_top
        has_top = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        if want_top != has_top:
            was_visible = self.isVisible()
            self._configure_window_flags()
            if was_visible:
                self.show()

        self.lbl_title.setText(self.config.title)
        self.lbl_title.setStyleSheet(f"color: {self.config.title_color};")

        scale_label = {
            "sqrt": "√-Skala",
            "dynamic": "Dyn-Peak",
            "fixed": "Max-Fix",
        }.get(self.config.scale_mode, "√-Skala")
        self.lbl_scale_badge.setText(scale_label)
        self.lbl_scale_badge.setStyleSheet(
            f"color: {self.config.title_color}; background-color: rgba(255,255,255,18); "
            "border-radius: 3px; padding: 1px 4px;"
        )

        down_col = self.config.download_color
        up_col = self.config.upload_color

        self.lbl_down_header.setStyleSheet(f"color: {down_col};")
        self.lbl_down_rate.setStyleSheet(f"color: {down_col};")
        self.lbl_down_meta.setStyleSheet(f"color: {self.config.title_color};")
        self.lbl_guest_down.setStyleSheet(f"color: {self.config.guest_download_color};")

        self.lbl_up_header.setStyleSheet(f"color: {up_col};")
        self.lbl_up_rate.setStyleSheet(f"color: {up_col};")
        self.lbl_up_meta.setStyleSheet(f"color: {self.config.title_color};")
        self.lbl_guest_up.setStyleSheet(f"color: {self.config.guest_upload_color};")

        self.bar_down_util.setStyleSheet(
            f"QProgressBar {{ background-color: rgba(255,255,255,22); border: none; border-radius: 2px; }} "
            f"QProgressBar::chunk {{ background-color: {down_col}; border-radius: 2px; }}"
        )
        self.bar_up_util.setStyleSheet(
            f"QProgressBar {{ background-color: rgba(255,255,255,22); border: none; border-radius: 2px; }} "
            f"QProgressBar::chunk {{ background-color: {up_col}; border-radius: 2px; }}"
        )

        self.lbl_footer.setStyleSheet(f"color: {self.config.title_color};")
        self.lbl_footer.setVisible(self.config.show_session_totals)
        self.size_grip.setVisible(not self.config.locked_pos and not self.config.compact_mode)

        is_counters = self.config.active_view == "counters"
        self.center_stack.setCurrentIndex(1 if is_counters else 0)
        self.lbl_scale_badge.setVisible(not is_counters and not self.config.compact_mode)
        self.counter_view.apply_theme()
        self._style_view_pills(is_counters)

        self._in_layout_transition = True
        try:
            if (
                not self._was_compact
                and self.config.compact_mode
                and self.isVisible()
                and self.height() >= 220
            ):
                self.config.widget_width = self.width()
                self.config.widget_height = self.height()

            # Minimum dimensions that fit both Graph & 5-row Online-Zähler with Ratio Bar
            min_w = 430 if is_counters else 260
            min_h = 285 if is_counters else 210
            target_w = max(min_w, self.config.widget_width)
            target_h = max(min_h, self.config.widget_height)

            if self.config.compact_mode:
                self.center_stack.setVisible(False)
                self.setMinimumWidth(260)
                self.setMinimumHeight(88)
                self.setMaximumHeight(115)
                self.resize(target_w, 98)
            else:
                self.center_stack.setVisible(True)
                self.setMinimumWidth(min_w)
                self.setMinimumHeight(min_h)
                self.setMaximumHeight(16777215)
                self.resize(target_w, target_h)

            self._was_compact = self.config.compact_mode
            self._was_counters = is_counters
        finally:
            self._in_layout_transition = False

        if hasattr(self, "_poll_timer"):
            self._poll_timer.setInterval(max(500, self.config.refresh_interval_sec * 1000))

        self.update()

    def _style_view_pills(self, is_counters: bool) -> None:
        """Style the header toggle buttons for Graph vs. Zähler view."""
        active_col = self.config.download_color
        qcol = QColor(active_col)
        lum = 0.299 * qcol.red() + 0.587 * qcol.green() + 0.114 * qcol.blue()
        active_text = "#111111" if lum > 140 else "#FFFFFF"

        active_css = (
            f"QPushButton {{ background-color: {active_col}; color: {active_text}; "
            "font-weight: bold; font-size: 9px; border: none; border-radius: 4px; padding: 1px 6px; }}"
        )
        inactive_css = (
            f"QPushButton {{ background-color: rgba(255,255,255,20); color: {self.config.title_color}; "
            "font-size: 9px; border: 1px solid rgba(255,255,255,35); border-radius: 4px; padding: 1px 6px; }}"
            "QPushButton:hover { background-color: rgba(255,255,255,38); }"
        )
        self.btn_view_graph.setStyleSheet(inactive_css if is_counters else active_css)
        self.btn_view_counters.setStyleSheet(active_css if is_counters else inactive_css)

    def _switch_active_view(self, view_name: str) -> None:
        """Switch between 'graph' and 'counters' view inside the widget."""
        self.config.active_view = view_name
        if self.config.compact_mode:
            self.config.compact_mode = False
        self.config.save()
        self._apply_config_visuals()
        self.counter_view.update_from_sample(self._last_sample)

    def _effective_max_bandwidths(self, sample: TrafficSample) -> tuple[float, float]:
        """Return (max_down_bps, max_up_bps) in bytes/sec according to Auto vs Manual config."""
        if self.config.auto_link_scale and sample.max_download_bps > 0:
            max_down = sample.max_download_bps
        else:
            max_down = max(1024.0, (self.config.manual_download_mbps * 1_000_000.0) / 8.0)

        if self.config.auto_link_scale and sample.max_upload_bps > 0:
            max_up = sample.max_upload_bps
        else:
            max_up = max(1024.0, (self.config.manual_upload_mbps * 1_000_000.0) / 8.0)

        return max_down, max_up

    @Slot(object)
    def _on_sample_received(self, sample: TrafficSample) -> None:
        """Update labels, utilization bars, graph, and tooltips with a fresh TrafficSample."""
        self._last_sample = sample
        self.lbl_icon.setPixmap(create_router_icon(sample.is_connected).pixmap(QSize(18, 18)))

        if not sample.is_connected and sample.error_message:
            self.lbl_down_rate.setText("Offline")
            self.lbl_up_rate.setText("Offline")
            self.graph_widget.push_sample(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            self._update_tooltip(sample, 0.0, 0.0)
            return

        self.graph_widget.push_sample(
            sample.download_bps,
            sample.upload_bps,
            sample.guest_download_bps,
            sample.guest_upload_bps,
            sample.max_download_bps,
            sample.max_upload_bps,
        )

        # Rolling peak across the visible graph window (auto-resets as spikes scroll out)
        self._peak_down_bps = self.graph_widget.current_peak_down_bps
        self._peak_up_bps = self.graph_widget.current_peak_up_bps

        bits = self.config.show_as_bits
        down_str = format_rate(sample.download_bps, bits)
        up_str = format_rate(sample.upload_bps, bits)

        self.lbl_down_rate.setText(down_str)
        self.lbl_up_rate.setText(up_str)

        max_down_bps, max_up_bps = self._effective_max_bandwidths(sample)
        down_pct = min(100.0, (sample.download_bps / max_down_bps) * 100.0) if max_down_bps > 0 else 0.0
        up_pct = min(100.0, (sample.upload_bps / max_up_bps) * 100.0) if max_up_bps > 0 else 0.0

        self.bar_down_util.setValue(int(down_pct * 10))
        self.bar_up_util.setValue(int(up_pct * 10))

        peak_down_str = format_rate(self._peak_down_bps, bits)
        peak_up_str = format_rate(self._peak_up_bps, bits)
        self.lbl_down_meta.setText(
            f"{down_pct:.1f}% • Peak (60s): {peak_down_str}".replace(".", ",")
        )
        self.lbl_up_meta.setText(
            f"{up_pct:.1f}% • Peak (60s): {peak_up_str}".replace(".", ",")
        )

        # Guest Wi-Fi readout (if enabled & active)
        if self.config.enable_guest_monitor and sample.guest_active:
            self.lbl_guest_down.setVisible(True)
            self.lbl_guest_up.setVisible(True)
            self.lbl_guest_down.setText(
                f"Gast: {format_rate(sample.guest_download_bps, bits)}"
            )
            self.lbl_guest_up.setText(
                f"Gast: {format_rate(sample.guest_upload_bps, bits)}"
            )
        else:
            self.lbl_guest_down.setVisible(False)
            self.lbl_guest_up.setVisible(False)

        # Footer (Online-Zähler or Session traffic)
        if self.config.show_session_totals:
            self.lbl_footer.setText(self._format_footer_text(sample))

        self.counter_view.update_from_sample(sample)

        self._update_tooltip(sample, down_pct, up_pct)

    def _format_footer_text(self, sample: TrafficSample) -> str:
        """Build the footer text for the selected Online-Zähler period or local session."""
        oc = sample.online_counters
        mode = self.config.footer_counter_mode
        if oc.is_available and mode != "session":
            period_map: dict[str, tuple[str, PeriodCounter]] = {
                "today": ("Heute", oc.today),
                "yesterday": ("Gestern", oc.yesterday),
                "week": ("Woche", oc.this_week),
                "month": ("Monat", oc.this_month),
                "last_month": ("Vormonat", oc.last_month),
            }
            label, counter = period_map.get(mode, ("Heute", oc.today))
            rx_str = format_bytes(counter.received_bytes)
            tx_str = format_bytes(counter.sent_bytes)
            tot_str = format_bytes(counter.total_bytes)
            return f"{label}: ⬇ {rx_str} • ⬆ {tx_str} (Σ {tot_str})"

        rx_str = format_bytes(sample.session_bytes_received)
        tx_str = format_bytes(sample.session_bytes_sent)
        return f"Seit Widget-Start: ⬇ {rx_str}  •  ⬆ {tx_str}"

    def _update_tooltip(
        self, sample: TrafficSample, down_pct: float, up_pct: float
    ) -> None:
        bits = self.config.show_as_bits
        down_str = format_rate(sample.download_bps, bits)
        up_str = format_rate(sample.upload_bps, bits)

        tray_tip = (
            f"TrafficBox ({self.config.fritzbox_host})\n"
            f"⬇ Down: {down_str} ({down_pct:.1f}%)\n"
            f"⬆ Up: {up_str} ({up_pct:.1f}%)"
        ).replace(".", ",")
        self.tray_icon.setToolTip(tray_tip)

        if not self.config.show_connection_tooltip:
            self.setToolTip("")
            return

        max_down_bps, max_up_bps = self._effective_max_bandwidths(sample)
        max_down_mbps = (max_down_bps * 8.0) / 1_000_000.0
        max_up_mbps = (max_up_bps * 8.0) / 1_000_000.0

        lines = [
            f"<b>Fritz!Box ({self.config.fritzbox_host})</b>",
            f"Status: <b>{sample.connection_status}</b> | Verbunden seit: {format_uptime(sample.uptime_seconds)}",
            f"Externe IP: <code>{sample.external_ip}</code>",
            f"Leitungskapazität: ⬇ {max_down_mbps:.1f} Mbit/s | ⬆ {max_up_mbps:.1f} Mbit/s".replace(
                ".", ","
            ),
            f"Seit Widget-Start: ⬇ {format_bytes(sample.session_bytes_received)} | ⬆ {format_bytes(sample.session_bytes_sent)}",
        ]

        oc = sample.online_counters
        if oc.is_available:
            rows = [
                ("Heute", oc.today),
                ("Gestern", oc.yesterday),
                ("Aktuelle Woche", oc.this_week),
                ("Aktueller Monat", oc.this_month),
                ("Vormonat", oc.last_month),
            ]
            table_html = (
                "<hr><b>Fritz!Box Online-Zähler:</b>"
                "<table cellspacing='4' cellpadding='1'>"
                "<tr><th align='left'>Zeitraum</th><th align='right'>Gesamt</th>"
                "<th align='right'>⬆ Gesendet</th><th align='right'>⬇ Empfangen</th></tr>"
            )
            for p_name, p_cnt in rows:
                table_html += (
                    f"<tr><td>{p_name}</td>"
                    f"<td align='right'><b>{format_bytes(p_cnt.total_bytes)}</b></td>"
                    f"<td align='right'>{format_bytes(p_cnt.sent_bytes)}</td>"
                    f"<td align='right'>{format_bytes(p_cnt.received_bytes)}</td></tr>"
                )
            table_html += "</table>"
            lines.append(table_html)
        else:
            uptime_str = format_uptime(sample.uptime_seconds)
            since_lbl = f"Seit Verbindung ({uptime_str})" if sample.uptime_seconds > 0 else "Seit Router-Start"
            lines.append(
                f"{since_lbl}: ⬇ {format_bytes(sample.total_bytes_received)} | ⬆ {format_bytes(sample.total_bytes_sent)}"
            )

        if sample.error_message:
            lines.append(f"<span style='color:#FF5252;'>Fehler: {sample.error_message}</span>")
        self.setToolTip("<br>".join(lines))

    def paintEvent(self, _event: object) -> None:
        """Draw the rounded translucent background and border of the widget."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        bg_color = QColor(self.config.background_color)
        alpha = int(max(20, min(100, self.config.opacity)) * 2.55)
        bg_color.setAlpha(alpha)

        border_color = QColor(self.config.border_color)
        border_color.setAlpha(min(255, alpha + 30))

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(bg_color)
        painter.setPen(QPen(border_color, 1.2))
        painter.drawRoundedRect(rect, 8.0, 8.0)

    # --- Mouse Interaction (Drag to move, Double-click for Settings, Right-click Menu) ---

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.config.locked_pos:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and not self.config.locked_pos
        ):
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self.move(new_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self.config.pos_x = self.x()
            self.config.pos_y = self.y()
            if not self.config.compact_mode:
                self.config.widget_width = self.width()
                self.config.widget_height = self.height()
            self.config.save()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        if (
            not self.config.compact_mode
            and not self._in_layout_transition
            and self.isVisible()
            and self.height() >= 210
        ):
            self.config.widget_width = self.width()
            self.config.widget_height = self.height()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_settings_dialog()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = self._build_context_menu()
        menu.exec(event.globalPos())

    def _build_context_menu(self) -> QMenu:
        menu = QMenu(self)

        act_settings = QAction("Einstellungen...", self)
        act_settings.triggered.connect(self.open_settings_dialog)
        menu.addAction(act_settings)

        menu.addSeparator()

        # Scaling Submenu
        scale_menu = menu.addMenu("Graph-Skalierung")
        scale_group = QActionGroup(self)
        for label, mode_key in [
            ("Wurzel-Skala (Smart)", "sqrt"),
            ("Dynamisch (Auto-Peak)", "dynamic"),
            ("Fix auf Leitungskapazität", "fixed"),
        ]:
            act = QAction(label, self, checkable=True)
            act.setChecked(self.config.scale_mode == mode_key)
            act.triggered.connect(lambda _chk=False, m=mode_key: self._set_scale_mode(m))
            scale_group.addAction(act)
            scale_menu.addAction(act)

        # Footer Counter Period Submenu
        footer_menu = menu.addMenu("Footer-Zähler (Zeitraum)")
        footer_group = QActionGroup(self)
        for f_label, f_key in [
            ("Heute (Online-Zähler)", "today"),
            ("Gestern (Online-Zähler)", "yesterday"),
            ("Aktuelle Woche (Online-Zähler)", "week"),
            ("Aktueller Monat (Online-Zähler)", "month"),
            ("Vormonat (Online-Zähler)", "last_month"),
            ("Seit Widget-Start (ohne Login)", "session"),
        ]:
            act_f = QAction(f_label, self, checkable=True)
            act_f.setChecked(self.config.footer_counter_mode == f_key)
            act_f.triggered.connect(lambda _chk=False, k=f_key: self._set_footer_mode(k))
            footer_group.addAction(act_f)
            footer_menu.addAction(act_f)

        act_bits = QAction("Als Bit/s anzeigen (Mbit/s)", self, checkable=True)
        act_bits.setChecked(self.config.show_as_bits)
        act_bits.triggered.connect(self._toggle_bits)
        menu.addAction(act_bits)

        act_compact = QAction("Kompakt-Modus (nur Zahlen)", self, checkable=True)
        act_compact.setChecked(self.config.compact_mode)
        act_compact.triggered.connect(self._toggle_compact)
        menu.addAction(act_compact)

        act_top = QAction("Immer im Vordergrund", self, checkable=True)
        act_top.setChecked(self.config.always_on_top)
        act_top.triggered.connect(self._toggle_always_on_top)
        menu.addAction(act_top)

        act_lock = QAction("Position sperren", self, checkable=True)
        act_lock.setChecked(self.config.locked_pos)
        act_lock.triggered.connect(self._toggle_lock_pos)
        menu.addAction(act_lock)

        menu.addSeparator()

        act_reset_session = QAction("Zähler „Seit Widget-Start“ zurücksetzen", self)
        act_reset_session.triggered.connect(self._reset_session_counter)
        menu.addAction(act_reset_session)

        act_hide = QAction(
            "Widget ausblenden" if self.isVisible() else "Widget einblenden", self
        )
        act_hide.triggered.connect(self._toggle_visibility)
        menu.addAction(act_hide)

        menu.addSeparator()

        act_quit = QAction("Beenden", self)
        act_quit.triggered.connect(self.quit_application)
        menu.addAction(act_quit)

        return menu

    def _set_scale_mode(self, mode: str) -> None:
        self.config.scale_mode = mode
        self.config.save()
        self._apply_config_visuals()

    def _set_footer_mode(self, mode: str) -> None:
        self.config.footer_counter_mode = mode
        self.config.save()
        self._on_sample_received(self._last_sample)

    def _toggle_bits(self, checked: bool) -> None:
        self.config.show_as_bits = checked
        self.config.save()
        self._on_sample_received(self._last_sample)

    def _toggle_compact(self, checked: bool) -> None:
        self.config.compact_mode = checked
        self.config.save()
        self._apply_config_visuals()

    def _toggle_always_on_top(self, checked: bool) -> None:
        self.config.always_on_top = checked
        self.config.save()
        self._apply_config_visuals()

    def _toggle_lock_pos(self, checked: bool) -> None:
        self.config.locked_pos = checked
        self.config.save()
        self._apply_config_visuals()

    def _reset_session_counter(self) -> None:
        self.request_reset_session.emit()
        self.request_poll.emit()

    def _toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._toggle_visibility()

    def open_settings_dialog(self) -> None:
        """Open or focus the Settings dialog."""
        if self._settings_dlg is not None and self._settings_dlg.isVisible():
            self._settings_dlg.raise_()
            self._settings_dlg.activateWindow()
            return

        self._settings_dlg = SettingsDialog(
            self.config,
            on_apply=self._on_settings_applied,
            parent=None,
        )
        self._settings_dlg.show()

    def _on_settings_applied(self) -> None:
        self._apply_config_visuals()
        self.request_poll.emit()

    def quit_application(self) -> None:
        """Cleanly stop worker thread, save position, and exit."""
        self.config.pos_x = self.x()
        self.config.pos_y = self.y()
        if not self.config.compact_mode:
            self.config.widget_width = self.width()
            self.config.widget_height = self.height()
        self.config.save()

        self._poll_timer.stop()
        self._worker_thread.quit()
        self._worker_thread.wait(1500)
        self.tray_icon.hide()
        QApplication.quit()
