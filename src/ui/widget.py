"""Main frameless floating TrafficBox Widget."""

from __future__ import annotations

import html
import sys

from PySide6.QtCore import (
    QObject,
    QPoint,
    QRect,
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
    QMoveEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSizeGrip,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.api.internet_health import HealthStatus, _format_dns_error
from src.api.models import OnlineCounterStats, PeriodCounter, TrafficSample
from src.api.net_health import set_shutting_down
from src.api.worker import PollingWorker
from src.autostart import sync_kwin_position_rule
from src.config import AppConfig
from src.ui.formatters import format_bytes, format_rate, format_uptime
from src.ui.graph_canvas import SplitTrafficGraphWidget
from src.ui.health_dialog import ClickablePillLabel, InternetHealthDialog
from src.ui.icons import create_arrow_pixmap, create_ui_icon
from src.ui.online_counter_view import OnlineCounterView
from src.ui.settings_dlg import SettingsDialog
from src.ui.tray import create_router_icon
from src.ui.widget_window import TrafficBoxWindowMixin, VisualSizeGrip


class TrafficBox(TrafficBoxWindowMixin, QWidget):
    """Frameless, translucent cross-platform desktop widget for live Fritz!Box traffic."""

    request_poll = Signal()
    request_reset_session = Signal()
    request_reload_credentials = Signal()
    request_health_probe = Signal()

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        set_shutting_down(False)
        self.config = config
        self._drag_start_pos: QPoint = QPoint()
        self._drag_offset: QPoint | None = None
        self._peak_down_bps: float = 0.0
        self._peak_up_bps: float = 0.0
        self._last_down_pct: float = 0.0
        self._last_up_pct: float = 0.0
        self._last_sample: TrafficSample = TrafficSample()
        self._settings_dlg: SettingsDialog | None = None
        self._health_dlg: InternetHealthDialog | None = None
        self._in_layout_transition: bool = False
        self._is_quitting: bool = False
        self._was_compact: bool = self.config.compact_mode
        self._was_counters: bool = self.config.active_view == "counters"
        self._user_is_moving: bool = False
        self._last_drag_pos: QPoint | None = None
        self._last_icon_led_color: str = ""

        self._save_pos_timer = QTimer(self)
        self._save_pos_timer.setSingleShot(True)
        self._save_pos_timer.timeout.connect(self._on_position_settled)

        self._configure_window_flags()
        self._build_ui()
        self._setup_tray_icon()
        self._apply_config_visuals()
        self._restore_geometry()
        self._setup_worker_thread()

    def _configure_window_flags(self) -> None:
        """Apply frameless, tool (hides from taskbar), and optional always-on-top window flags."""
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

        self.btn_view_graph = QPushButton(" Graph")
        self.btn_view_graph.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_view_graph.setFixedHeight(20)
        self.btn_view_graph.clicked.connect(lambda: self._switch_active_view("graph"))

        self.btn_view_counters = QPushButton(" Zähler")
        self.btn_view_counters.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_view_counters.setFixedHeight(20)
        self.btn_view_counters.clicked.connect(lambda: self._switch_active_view("counters"))

        self.btn_settings = QPushButton()
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.setFixedSize(20, 20)
        self.btn_settings.setToolTip("Einstellungen...")
        self.btn_settings.clicked.connect(self.open_settings_dialog)

        header_row.addWidget(self.lbl_icon)
        header_row.addWidget(self.lbl_title)
        header_row.addStretch(1)
        header_row.addWidget(self.btn_view_graph)
        header_row.addWidget(self.btn_view_counters)
        header_row.addWidget(self.btn_settings)
        self.main_layout.addLayout(header_row)

        # --- 2. Live Rate Readouts + Utilization % Bars (Down & Up) ---
        self.rates_container = QWidget(self)
        rates_row = QHBoxLayout(self.rates_container)
        rates_row.setContentsMargins(2, 0, 2, 2)
        rates_row.setSpacing(10)

        # Download Column
        down_col = QVBoxLayout()
        down_col.setSpacing(2)

        down_hdr_row = QHBoxLayout()
        down_hdr_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        down_hdr_row.setSpacing(4)
        down_hdr_row.setContentsMargins(0, 0, 0, 0)
        self.icon_down_header = QLabel()
        self.icon_down_header.setFixedSize(11, 11)
        self.lbl_down_header = QLabel("Down:")
        self.lbl_down_header.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        down_hdr_row.addWidget(self.icon_down_header)
        down_hdr_row.addWidget(self.lbl_down_header)

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

        self.lbl_pc_down = QLabel("")
        self.lbl_pc_down.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_pc_down.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        self.lbl_pc_down.setVisible(False)

        self.lbl_guest_down = QLabel("")
        self.lbl_guest_down.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_guest_down.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        self.lbl_guest_down.setVisible(False)

        down_col.addLayout(down_hdr_row)
        down_col.addWidget(self.lbl_down_rate)
        down_col.addWidget(self.bar_down_util)
        down_col.addWidget(self.lbl_down_meta)
        down_col.addWidget(self.lbl_pc_down)
        down_col.addWidget(self.lbl_guest_down)

        # Upload Column
        up_col = QVBoxLayout()
        up_col.setSpacing(2)

        up_hdr_row = QHBoxLayout()
        up_hdr_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        up_hdr_row.setSpacing(4)
        up_hdr_row.setContentsMargins(0, 0, 0, 0)
        self.icon_up_header = QLabel()
        self.icon_up_header.setFixedSize(11, 11)
        self.lbl_up_header = QLabel("Up:")
        self.lbl_up_header.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        up_hdr_row.addWidget(self.icon_up_header)
        up_hdr_row.addWidget(self.lbl_up_header)

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

        self.lbl_pc_up = QLabel("")
        self.lbl_pc_up.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_pc_up.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        self.lbl_pc_up.setVisible(False)

        self.lbl_guest_up = QLabel("")
        self.lbl_guest_up.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_guest_up.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        self.lbl_guest_up.setVisible(False)

        up_col.addLayout(up_hdr_row)
        up_col.addWidget(self.lbl_up_rate)
        up_col.addWidget(self.bar_up_util)
        up_col.addWidget(self.lbl_up_meta)
        up_col.addWidget(self.lbl_pc_up)
        up_col.addWidget(self.lbl_guest_up)

        rates_row.addLayout(down_col, 1)
        rates_row.addLayout(up_col, 1)
        self.main_layout.addWidget(self.rates_container)

        # --- 3. Center Stacked Area (Split Graph vs. Online-Zähler Table) ---
        self.center_stack = QStackedWidget(self)
        self.graph_widget = SplitTrafficGraphWidget(self.config, self)
        self.counter_view = OnlineCounterView(
            self.config, on_open_settings=self.open_settings_dialog, parent=self
        )
        self.center_stack.addWidget(self.graph_widget)
        self.center_stack.addWidget(self.counter_view)
        self.main_layout.addWidget(self.center_stack, 1)

        # --- 4. Footer Row (Calm UI 3-Pill Bar + Resize Grip) ---
        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(2, 2, 0, 0)
        footer_row.setSpacing(5)

        self.lbl_wan_pill = ClickablePillLabel("✓ WAN OK")
        self.lbl_wan_pill.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        self.lbl_wan_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_wan_pill.clicked.connect(self.open_health_dialog)

        self.lbl_footer = QLabel("Heute: 0 B")
        self.lbl_footer.setFont(QFont("Segoe UI", 7))
        self.lbl_footer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.footer_spacer = QWidget(self)
        self.footer_spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.lbl_dns_pill = ClickablePillLabel("✓ DNS")
        self.lbl_dns_pill.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        self.lbl_dns_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_dns_pill.clicked.connect(self.open_health_dialog)

        self.size_grip = VisualSizeGrip(self)

        footer_row.addWidget(self.lbl_wan_pill, 0)
        footer_row.addWidget(self.lbl_footer, 1)
        footer_row.addWidget(self.footer_spacer, 1)
        footer_row.addWidget(self.lbl_dns_pill, 0)
        footer_row.addWidget(
            self.size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight
        )
        self.main_layout.addLayout(footer_row)

    def _setup_tray_icon(self) -> None:
        self.tray_icon = QSystemTrayIcon(create_router_icon(True), self)
        self.tray_icon.setToolTip("TrafficBox")
        self.tray_icon.setContextMenu(self._build_context_menu())
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _setup_worker_thread(self) -> None:
        self._worker_thread = QThread(self)
        self._worker = PollingWorker(self.config)
        self._worker.moveToThread(self._worker_thread)

        self.request_poll.connect(self._worker.poll_once)
        self.request_reset_session.connect(self._worker.reset_session)
        self.request_reload_credentials.connect(self._worker.reload_credentials)
        self.request_health_probe.connect(self._worker.trigger_health_probe)
        self._worker.sample_ready.connect(self._on_sample_received)

        self._worker_thread.start()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.request_poll.emit)

        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.aboutToQuit.connect(self._on_app_about_to_quit)
            app.commitDataRequest.connect(self._on_commit_data_request)

        delay_ms = max(0, self.config.start_delay_sec * 1000)
        QTimer.singleShot(delay_ms, self._start_polling)

    def _start_polling(self) -> None:
        if self._is_quitting:
            return
        self.request_poll.emit()
        interval_ms = max(500, self.config.refresh_interval_sec * 1000)
        self._poll_timer.start(interval_ms)

    def _get_compact_height(self) -> int:
        """Calculate the required compact mode height to prevent element overlapping."""
        base_scale = self.config.ui_scale
        extra = 0
        if self.config.enable_local_traffic_monitor and self.config.show_local_traffic_in_header:
            extra += int(round(14.0 * base_scale))
        if self.config.enable_guest_monitor and self.config.show_guest_rate_labels:
            extra += int(round(14.0 * base_scale))
        min_h = self.minimumSizeHint().height()
        return max(min_h + 6, int(round(122.0 * base_scale)) + extra)

    def _on_position_settled(self) -> None:
        """Persist window position to disk and update KWin rules on Linux/Wayland."""
        self._user_is_moving = False
        self._last_drag_pos = None
        if self.isVisible() and self.config.pos_x >= 0 and self.config.pos_y >= 0:
            self.config.save()
            if sys.platform == "linux":
                sync_kwin_position_rule(self.config.pos_x, self.config.pos_y)

    def _restore_geometry(self) -> None:
        base_scale = self.config.ui_scale
        min_w = int(round(260.0 * base_scale))
        min_h = int(round(210.0 * base_scale))
        w = max(min_w, self.config.widget_width)
        h = self._get_compact_height() if self.config.compact_mode else max(min_h, self.config.widget_height)
        self.resize(w, h)

        if sys.platform == "linux" and self.config.pos_x >= 0 and self.config.pos_y >= 0:
            sync_kwin_position_rule(self.config.pos_x, self.config.pos_y)

        target_pos = QPoint(self.config.pos_x, self.config.pos_y)
        is_on_screen = False
        if self.config.pos_x >= 0 and self.config.pos_y >= 0:
            for s in QApplication.screens():
                if s.availableGeometry().intersects(QRect(target_pos, QSize(w, h))):
                    is_on_screen = True
                    break

        if is_on_screen:
            self.move(target_pos)
            # Re-apply position slightly deferred after mapping to override aggressive compositor centering
            QTimer.singleShot(150, lambda: self.move(target_pos))
        else:
            screen = QApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                default_pos = QPoint(avail.right() - w - 24, avail.bottom() - h - 24)
                self.move(default_pos)
                QTimer.singleShot(150, lambda: self.move(default_pos))

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

        down_col = self.config.download_color
        up_col = self.config.upload_color

        self.icon_down_header.setPixmap(create_arrow_pixmap(down_col, "down", 11))
        self.lbl_down_header.setStyleSheet(f"color: {down_col};")
        self.lbl_down_rate.setStyleSheet(f"color: {down_col};")
        self.lbl_down_meta.setStyleSheet(f"color: {self.config.title_color};")
        self.lbl_guest_down.setStyleSheet(f"color: {self.config.guest_download_color};")

        self.icon_up_header.setPixmap(create_arrow_pixmap(up_col, "up", 11))
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

        bg_col = QColor(self.config.background_color)
        bg_lum = (
            0.299 * bg_col.red() + 0.587 * bg_col.green() + 0.114 * bg_col.blue()
            if bg_col.isValid()
            else 30.0
        )
        if bg_lum > 140.0:
            self.setStyleSheet(
                "QToolTip { background-color: #F8FAFC; color: #1E293B; "
                "border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px 8px; }"
            )
        else:
            self.setStyleSheet(
                "QToolTip { background-color: #141A20; color: #E2E8F0; "
                "border: 1px solid #384450; border-radius: 6px; padding: 6px 8px; }"
            )

        footer_css = (
            f"QLabel {{ color: {self.config.title_color}; "
            "background-color: rgba(255, 255, 255, 12); "
            "border: 1px solid rgba(255, 255, 255, 24); "
            "border-radius: 9px; padding: 1px 7px; }}"
        )
        self.lbl_footer.setStyleSheet(footer_css)
        self.lbl_footer.setVisible(self.config.show_session_totals)
        self.footer_spacer.setVisible(not self.config.show_session_totals)
        self.lbl_wan_pill.setVisible(self.config.show_wan_status_pill)
        self.lbl_dns_pill.setVisible(self.config.enable_dns_monitor)
        self.size_grip.setVisible(not self.config.locked_pos and not self.config.compact_mode)

        is_counters = self.config.active_view == "counters"
        self.center_stack.setCurrentIndex(1 if is_counters else 0)
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

            # Minimum dimensions: identical 260px width for both Graph & Online-Zähler scaled to UI factor
            base_scale = self.config.ui_scale
            min_w = int(round(260.0 * base_scale))
            if is_counters:
                min_h = int(round(295.0 * base_scale))
            elif self.config.graph_only_mode:
                min_h = int(round(160.0 * base_scale))
            else:
                min_h = int(round(210.0 * base_scale))

            target_w = max(min_w, self.config.widget_width)
            target_h = max(min_h, self.config.widget_height)

            if self.config.compact_mode:
                self.rates_container.setVisible(True)
                self.center_stack.setVisible(False)
                compact_h = self._get_compact_height()
                self.setMinimumWidth(min_w)
                self.setMinimumHeight(compact_h)
                self.setMaximumHeight(compact_h + int(round(25.0 * base_scale)))
                self.resize(target_w, compact_h)
            elif self.config.graph_only_mode:
                self.rates_container.setVisible(False)
                self.center_stack.setVisible(True)
                self.setMinimumWidth(min_w)
                self.setMinimumHeight(min_h)
                self.setMaximumHeight(16777215)
                self.resize(target_w, target_h)
            else:
                self.rates_container.setVisible(True)
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

        # Coupled darker shade for PC labels
        pc_down_col = QColor(self.config.download_color).darker(125).name()
        pc_up_col = QColor(self.config.upload_color).darker(125).name()
        self.lbl_pc_down.setStyleSheet(f"color: {pc_down_col};")
        self.lbl_pc_up.setStyleSheet(f"color: {pc_up_col};")

        if not (self.config.enable_local_traffic_monitor and self.config.show_local_traffic_in_header):
            self.lbl_pc_down.setVisible(False)
            self.lbl_pc_up.setVisible(False)

        if not (self.config.enable_guest_monitor and self.config.show_guest_rate_labels):
            self.lbl_guest_down.setVisible(False)
            self.lbl_guest_up.setVisible(False)
        if self._last_sample:
            self._update_live_rate_displays(self._last_sample)

        self._update_dynamic_scaling()
        if hasattr(self, "tray_icon") and self.tray_icon is not None:
            self.tray_icon.setContextMenu(self._build_context_menu())
        self.update()

    def _get_status_palette(self, status: HealthStatus, is_connected: bool = True) -> tuple[str, str, str, str]:
        """Return theme- and contrast-aware (text_hex, bg_rgba, border_rgba, led_hex) for health pills."""
        bg_col = QColor(self.config.background_color)
        bg_lum = (
            0.299 * bg_col.red() + 0.587 * bg_col.green() + 0.114 * bg_col.blue()
            if bg_col.isValid()
            else 30.0
        )
        is_light_bg = bg_lum > 140.0

        down_q = QColor(self.config.download_color)
        guest_q = QColor(self.config.guest_download_color)
        is_monochrome = (
            down_q.isValid()
            and down_q.hsvSaturation() < 45
            and guest_q.isValid()
            and guest_q.hsvSaturation() < 45
        )

        if status == HealthStatus.STABLE:
            if is_monochrome:
                if is_light_bg:
                    return (
                        self.config.title_color,
                        "rgba(0, 0, 0, 0.08)",
                        "rgba(0, 0, 0, 0.25)",
                        "#1B7F46",
                    )
                return (
                    self.config.title_color,
                    "rgba(255, 255, 255, 0.08)",
                    "rgba(255, 255, 255, 0.25)",
                    "#00E676",
                )
            if is_light_bg:
                return ("#1B7F46", "rgba(27, 127, 70, 0.14)", "rgba(27, 127, 70, 0.42)", "#1B7F46")
            return ("#00E676", "rgba(0, 230, 118, 0.12)", "rgba(0, 230, 118, 0.38)", "#00E676")

        if status == HealthStatus.DEGRADED:
            if is_light_bg:
                return ("#B26A00", "rgba(178, 106, 0, 0.14)", "rgba(178, 106, 0, 0.42)", "#B26A00")
            return ("#FFAB00", "rgba(255, 171, 0, 0.16)", "rgba(255, 171, 0, 0.45)", "#FFAB00")

        if status == HealthStatus.DNS_ERROR:
            if is_light_bg:
                return ("#C84316", "rgba(200, 67, 22, 0.14)", "rgba(200, 67, 22, 0.42)", "#C84316")
            return ("#FF7043", "rgba(255, 112, 67, 0.16)", "rgba(255, 112, 67, 0.45)", "#FF7043")

        if status in (HealthStatus.OFFLINE, HealthStatus.ZOMBIE_WAN):
            if is_light_bg:
                return ("#C62828", "rgba(198, 40, 40, 0.14)", "rgba(198, 40, 40, 0.42)", "#C62828")
            return ("#FF5252", "rgba(255, 82, 82, 0.16)", "rgba(255, 82, 82, 0.45)", "#FF5252")

        if status == HealthStatus.LAN_ERROR:
            if is_light_bg:
                return ("#6A1B9A", "rgba(106, 27, 154, 0.14)", "rgba(106, 27, 154, 0.42)", "#6A1B9A")
            return ("#BB86FC", "rgba(187, 134, 252, 0.16)", "rgba(187, 134, 252, 0.45)", "#BB86FC")

        # UNKNOWN / Neutral
        led = ("#1B7F46" if is_light_bg else "#00E676") if is_connected else ("#C62828" if is_light_bg else "#FF5252")
        if is_light_bg:
            return (self.config.title_color, "rgba(0, 0, 0, 0.06)", "rgba(0, 0, 0, 0.20)", led)
        return (self.config.title_color, "rgba(255, 255, 255, 0.07)", "rgba(255, 255, 255, 0.22)", led)

    def _effective_status_led_color(self, sample: TrafficSample | None) -> str:
        """Resolve the router icon status LED hex color from health state or link flags."""
        if sample is None:
            return self._get_status_palette(HealthStatus.STABLE, True)[3]
        if self.config.enable_internet_health and sample.health.status != HealthStatus.UNKNOWN:
            return self._get_status_palette(sample.health.status, sample.is_connected)[3]
        if sample.is_local_fallback or not sample.physical_link_up or not sample.wan_connected:
            return self._get_status_palette(HealthStatus.DEGRADED, sample.is_connected)[3]
        if not sample.box_reachable:
            return self._get_status_palette(HealthStatus.OFFLINE, False)[3]
        return self._get_status_palette(HealthStatus.STABLE, True)[3]

    def _get_pill_style(self, text_col: str, bg_col: str, border_col: str, is_bold: bool = True) -> str:
        """Return responsive stylesheet for footer status pills (WAN/DNS) scaled to HiDPI."""
        base_scale = self.config.ui_scale
        radius = max(6, int(round(9.0 * base_scale)))
        pad_v = max(1, int(round(1.5 * base_scale)))
        pad_h = max(4, int(round(7.0 * base_scale)))
        bold_css = " font-weight: bold;" if is_bold else ""
        return (
            f"QLabel {{ color: {text_col}; background-color: {bg_col}; "
            f"border: 1px solid {border_col}; border-radius: {radius}px; "
            f"padding: {pad_v}px {pad_h}px;{bold_css} }}"
        )

    def _update_dynamic_scaling(self) -> None:
        """Dynamically scale fonts, bar heights, and icons based on widget dimensions and UI scale."""
        base_scale = self.config.ui_scale
        w = max(int(round(260.0 * base_scale)), self.width())
        h = max(int(round(180.0 * base_scale)), self.height())

        # Scale factor relative to baseline 420x270, clamped between 0.82 and 1.50
        dim_scale = max(0.82, min(1.50, (w / (420.0 * base_scale)) * 0.55 + (h / (270.0 * base_scale)) * 0.45))
        scale = base_scale * dim_scale

        # 0. Header Bar Elements (Icon, Title, Buttons)
        hdr_icon_sz = max(14, int(round(18.0 * base_scale)))
        is_conn = self._last_sample.is_connected if self._last_sample else True
        led_col = self._effective_status_led_color(self._last_sample)
        self.lbl_icon.setPixmap(
            create_router_icon(is_conn, status_color=led_col).pixmap(QSize(hdr_icon_sz, hdr_icon_sz))
        )
        title_pt = max(8, int(round(10.0 * base_scale)))
        self.lbl_title.setFont(QFont("Segoe UI", title_pt, QFont.Weight.Bold))
        is_counters = self.config.active_view == "counters"
        self._style_view_pills(is_counters)

        # 1. Live Rate Readouts: 9pt (compact) up to 15pt (large) scaled
        rate_pt = max(8, int(round(10.5 * scale)))
        rate_font = QFont("Segoe UI", rate_pt, QFont.Weight.Bold)
        self.lbl_down_rate.setFont(rate_font)
        self.lbl_up_rate.setFont(rate_font)

        # 2. Header Rate Utilization Bars: 4px to 8px scaled
        bar_h = max(3, int(round(5.0 * scale)))
        self.bar_down_util.setFixedHeight(bar_h)
        self.bar_up_util.setFixedHeight(bar_h)

        # 3. Meta Labels & PC/Guest labels
        meta_pt = max(6, int(round(7.5 * scale)))
        meta_font = QFont("Segoe UI", meta_pt)
        self.lbl_down_meta.setFont(meta_font)
        self.lbl_up_meta.setFont(meta_font)

        sub_font = QFont("Segoe UI", meta_pt, QFont.Weight.DemiBold)
        self.lbl_pc_down.setFont(sub_font)
        self.lbl_pc_up.setFont(sub_font)
        self.lbl_guest_down.setFont(sub_font)
        self.lbl_guest_up.setFont(sub_font)

        # 4. Header Arrow Icons & Labels
        arrow_icon_sz = max(9, int(round(11.0 * scale)))
        self.icon_down_header.setFixedSize(arrow_icon_sz, arrow_icon_sz)
        self.icon_up_header.setFixedSize(arrow_icon_sz, arrow_icon_sz)
        self.icon_down_header.setPixmap(create_arrow_pixmap(self.config.download_color, "down", arrow_icon_sz))
        self.icon_up_header.setPixmap(create_arrow_pixmap(self.config.upload_color, "up", arrow_icon_sz))

        hdr_pt = max(7, int(round(9.0 * scale)))
        self.lbl_down_header.setFont(QFont("Segoe UI", hdr_pt, QFont.Weight.DemiBold))
        self.lbl_up_header.setFont(QFont("Segoe UI", hdr_pt, QFont.Weight.DemiBold))

        # 5. Footer Pill Fonts scaling
        footer_pt = max(6, int(round(7.2 * scale)))
        self.lbl_footer.setFont(QFont("Segoe UI", footer_pt))
        pill_font = QFont("Segoe UI", footer_pt, QFont.Weight.DemiBold)
        self.lbl_wan_pill.setFont(pill_font)
        self.lbl_dns_pill.setFont(pill_font)

        # 6. Online Counter View scaling
        self.counter_view.set_scale(scale)

        # 7. SizeGrip scaling
        if hasattr(self, "size_grip") and hasattr(self.size_grip, "update_scale"):
            self.size_grip.update_scale(base_scale)

        # 8. Update footer elements responsive text if last sample is available
        if self._last_sample:
            if self.config.show_session_totals:
                self.lbl_footer.setText(self._format_footer_text(self._last_sample))
            self._update_wan_status_pill(self._last_sample)
            self._update_dns_pill(self._last_sample)

    def _style_view_pills(self, is_counters: bool) -> None:
        """Style the header toggle buttons for Graph vs. Zähler view with custom vector icons."""
        base_scale = self.config.ui_scale
        active_col = self.config.download_color
        qcol = QColor(active_col)
        lum = 0.299 * qcol.red() + 0.587 * qcol.green() + 0.114 * qcol.blue()
        active_text = "#111111" if lum > 140 else "#FFFFFF"

        # In compact mode, neither view tab is currently shown (center stack is hidden)
        is_compact = self.config.compact_mode
        graph_active = not is_counters and not is_compact
        counters_active = is_counters and not is_compact

        graph_icon_col = active_text if graph_active else self.config.title_color
        counters_icon_col = active_text if counters_active else self.config.title_color

        btn_icon_sz = max(15, int(round(18.0 * base_scale)))
        btn_h = max(26, int(round(30.0 * base_scale)))
        btn_font_px = max(11, int(round(13.0 * base_scale)))
        btn_radius = max(4, int(round(5.0 * base_scale)))
        pad_v = max(2, int(round(3.0 * base_scale)))
        pad_h = max(7, int(round(9.0 * base_scale)))
        settings_sz = btn_h

        self.btn_view_graph.setFixedHeight(btn_h)
        self.btn_view_counters.setFixedHeight(btn_h)
        self.btn_settings.setFixedSize(settings_sz, settings_sz)

        self.btn_view_graph.setIcon(create_ui_icon("graph", graph_icon_col, btn_icon_sz))
        self.btn_view_graph.setIconSize(QSize(btn_icon_sz, btn_icon_sz))
        self.btn_view_counters.setIcon(create_ui_icon("counters", counters_icon_col, btn_icon_sz))
        self.btn_view_counters.setIconSize(QSize(btn_icon_sz, btn_icon_sz))
        self.btn_settings.setIcon(create_ui_icon("settings", self.config.title_color, btn_icon_sz))
        self.btn_settings.setIconSize(QSize(btn_icon_sz, btn_icon_sz))

        active_css = (
            f"QPushButton {{ background-color: {active_col}; color: {active_text}; "
            f"font-weight: bold; font-size: {btn_font_px}px; border: none; border-radius: {btn_radius}px; padding: {pad_v}px {pad_h}px; }}"
        )
        inactive_css = (
            f"QPushButton {{ background-color: rgba(255,255,255,20); color: {self.config.title_color}; "
            f"font-size: {btn_font_px}px; border: 1px solid rgba(255,255,255,35); border-radius: {btn_radius}px; padding: {pad_v}px {pad_h}px; }} "
            "QPushButton:hover { background-color: rgba(255,255,255,38); }"
        )
        settings_css = (
            f"QPushButton {{ background-color: rgba(255,255,255,20); border: 1px solid rgba(255,255,255,35); "
            f"border-radius: {btn_radius}px; padding: {pad_v}px; }} "
            "QPushButton:hover { background-color: rgba(255,255,255,38); }"
        )
        self.btn_view_graph.setStyleSheet(active_css if graph_active else inactive_css)
        self.btn_view_counters.setStyleSheet(active_css if counters_active else inactive_css)
        self.btn_settings.setStyleSheet(settings_css)

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
        if sample.is_local_fallback and self.config.auto_link_scale:
            return (
                self.graph_widget.current_ceiling_down_bps,
                self.graph_widget.current_ceiling_up_bps,
            )

        if self.config.auto_link_scale and sample.max_download_bps > 0:
            max_down = sample.max_download_bps
        else:
            max_down = max(1024.0, (self.config.manual_download_mbps * 1_000_000.0) / 8.0)

        if self.config.auto_link_scale and sample.max_upload_bps > 0:
            max_up = sample.max_upload_bps
        else:
            max_up = max(1024.0, (self.config.manual_upload_mbps * 1_000_000.0) / 8.0)

        return max_down, max_up

    def _update_live_rate_displays(self, sample: TrafficSample) -> tuple[float, float]:
        """Update top rate numbers, utilization bars, and meta text for live traffic."""
        max_down_bps, max_up_bps = self._effective_max_bandwidths(sample)
        down_pct = min(100.0, (sample.download_bps / max_down_bps) * 100.0) if (max_down_bps > 0 and sample.is_connected) else 0.0
        up_pct = min(100.0, (sample.upload_bps / max_up_bps) * 100.0) if (max_up_bps > 0 and sample.is_connected) else 0.0

        self.lbl_down_header.setText("Down:")
        self.lbl_up_header.setText("Up:")

        bits = self.config.show_as_bits
        down_str = format_rate(sample.download_bps, bits)
        up_str = format_rate(sample.upload_bps, bits)

        if not sample.box_reachable and not sample.is_local_fallback:
            self.lbl_down_rate.setText("Offline")
            self.lbl_up_rate.setText("Offline")
        elif sample.is_local_fallback:
            self.lbl_down_rate.setText(down_str)
            self.lbl_up_rate.setText(up_str)
        elif not sample.physical_link_up:
            self.lbl_down_rate.setText("Kein Sync")
            self.lbl_up_rate.setText("Kein Sync")
        elif not sample.wan_connected:
            self.lbl_down_rate.setText("Kein Internet")
            self.lbl_up_rate.setText("Kein Internet")
        else:
            self.lbl_down_rate.setText(down_str)
            self.lbl_up_rate.setText(up_str)

        self.bar_down_util.setValue(int(down_pct * 10))
        self.bar_up_util.setValue(int(up_pct * 10))

        if self.config.show_peak_rate:
            sec = self.config.history_seconds
            peak_down_str = format_rate(self._peak_down_bps, bits)
            peak_up_str = format_rate(self._peak_up_bps, bits)
            self.lbl_down_meta.setText(
                f"{down_pct:.1f}% • Peak ({sec}s): {peak_down_str}".replace(".", ",")
            )
            self.lbl_up_meta.setText(
                f"{up_pct:.1f}% • Peak ({sec}s): {peak_up_str}".replace(".", ",")
            )
        else:
            self.lbl_down_meta.setText(f"{down_pct:.1f}%".replace(".", ","))
            self.lbl_up_meta.setText(f"{up_pct:.1f}%".replace(".", ","))

        return down_pct, up_pct

    @Slot(object)
    def _on_sample_received(self, sample: TrafficSample) -> None:
        """Update labels, utilization bars, graph, and tooltips with a fresh TrafficSample."""
        self._last_sample = sample
        hdr_icon_sz = max(14, int(round(18.0 * self.config.ui_scale)))
        led_col = self._effective_status_led_color(sample)
        router_icon = create_router_icon(sample.is_connected, status_color=led_col)
        self.lbl_icon.setPixmap(router_icon.pixmap(QSize(hdr_icon_sz, hdr_icon_sz)))
        if led_col != self._last_icon_led_color and hasattr(self, "tray_icon"):
            self._last_icon_led_color = led_col
            self.tray_icon.setIcon(router_icon)
            self.setWindowIcon(router_icon)

        self.graph_widget.push_sample(
            sample.download_bps if sample.is_connected else 0.0,
            sample.upload_bps if sample.is_connected else 0.0,
            sample.guest_download_bps if sample.is_connected else 0.0,
            sample.guest_upload_bps if sample.is_connected else 0.0,
            sample.max_download_bps,
            sample.max_upload_bps,
            ping_ms=sample.ping_ms,
            jitter_ms=sample.jitter_ms,
            pc_down_bps=sample.local_pc_download_bps if (sample.is_connected and not sample.is_local_fallback) else 0.0,
            pc_up_bps=sample.local_pc_upload_bps if (sample.is_connected and not sample.is_local_fallback) else 0.0,
            is_local_fallback=sample.is_local_fallback,
            ping_lost=sample.ping_lost,
        )

        # Rolling peak across the visible graph window (auto-resets as spikes scroll out)
        self._peak_down_bps = self.graph_widget.current_peak_down_bps
        self._peak_up_bps = self.graph_widget.current_peak_up_bps

        down_pct, up_pct = self._update_live_rate_displays(sample)

        bits = self.config.show_as_bits

        # Local PC readout (if enabled & active & allowed in header, but not redundant in fallback mode)
        if (
            self.config.enable_local_traffic_monitor
            and self.config.show_local_traffic_in_header
            and sample.local_pc_active
            and not sample.is_local_fallback
        ):
            self.lbl_pc_down.setVisible(True)
            self.lbl_pc_up.setVisible(True)
            lan_tag = " [LAN]" if sample.local_pc_is_lan_spike else ""
            self.lbl_pc_down.setText(
                f"PC: {format_rate(sample.local_pc_download_bps, bits)}{lan_tag}"
            )
            self.lbl_pc_up.setText(
                f"PC: {format_rate(sample.local_pc_upload_bps, bits)}{lan_tag}"
            )
        else:
            self.lbl_pc_down.setVisible(False)
            self.lbl_pc_up.setVisible(False)

        # Guest Wi-Fi readout (if enabled & active & allowed in header)
        if (
            self.config.enable_guest_monitor
            and self.config.show_guest_rate_labels
            and sample.guest_active
        ):
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

        # Ensure compact mode height expands if extra labels (PC/Guest) become visible
        if self.config.compact_mode and not self._in_layout_transition:
            needed_h = self._get_compact_height()
            if self.height() != needed_h:
                self.setMinimumHeight(needed_h)
                self.setMaximumHeight(needed_h + int(round(25.0 * self.config.ui_scale)))
                self.resize(self.width(), needed_h)

        # 1. WAN Status Pill (✓ / ⚠ / ✕)
        self._update_wan_status_pill(sample)

        # 2. Volume Footer Pill (Online-Zähler or Session traffic)
        if self.config.show_session_totals:
            self.lbl_footer.setText(self._format_footer_text(sample))

        # 3. Active OS DNS Status Pill (✓ / ⚠ / ✕)
        self._update_dns_pill(sample)

        self.counter_view.update_from_sample(sample)

        self._last_down_pct = down_pct
        self._last_up_pct = up_pct
        self._update_tooltip(sample, down_pct, up_pct)

        if self._health_dlg is not None and self._health_dlg.isVisible():
            self._health_dlg.update_from_sample(sample, down_pct, up_pct)

    def _update_wan_status_pill(self, sample: TrafficSample) -> None:
        """Update text, colors and tooltip of the WAN/Internet health status pill with HiDPI styling."""
        if self.config.enable_internet_health and sample.health.status != HealthStatus.UNKNOWN:
            st = sample.health.status
            txt_col, bg_col, border_col, _ = self._get_status_palette(st, sample.is_connected)
            if st == HealthStatus.STABLE:
                label = "⚡ Lokal • OK" if sample.is_local_fallback else "✓ Stabil"
            elif st == HealthStatus.DEGRADED:
                wide = self.width() >= int(round(360.0 * self.config.ui_scale))
                tag = sample.health.short_tag
                label = f"⚠ {tag}" if (wide and tag) else "⚠ Eingeschränkt"
            elif st == HealthStatus.DNS_ERROR:
                label = "⚠ DNS-Störung"
            elif st == HealthStatus.ZOMBIE_WAN:
                label = "✕ Kein Internet"
            elif st == HealthStatus.OFFLINE:
                if sample.box_reachable and not sample.is_local_fallback and not sample.physical_link_up:
                    label = "⚠ Kein Sync"
                elif sample.box_reachable and not sample.is_local_fallback and not sample.wan_connected:
                    label = "⚠ Kein Internet"
                elif sample.health.captive_portal_detected:
                    label = "⚠ Captive Portal"
                else:
                    label = "✕ Offline"
            else:  # LAN_ERROR
                if not sample.box_reachable and not sample.is_local_fallback and not sample.health.gateway_ip:
                    label = "✕ Box Offline"
                else:
                    label = "✕ LAN-Problem"

            self.lbl_wan_pill.setText(label)
            self.lbl_wan_pill.setStyleSheet(self._get_pill_style(txt_col, bg_col, border_col))
            return

        if sample.is_local_fallback:
            pal = self._get_status_palette(HealthStatus.DEGRADED, True)
            self.lbl_wan_pill.setText("⚡ Lokal (ohne Box)")
            self.lbl_wan_pill.setStyleSheet(self._get_pill_style(pal[0], pal[1], pal[2]))
        elif not sample.box_reachable:
            pal = self._get_status_palette(HealthStatus.OFFLINE, False)
            self.lbl_wan_pill.setText("✕ Box Offline")
            self.lbl_wan_pill.setStyleSheet(self._get_pill_style(pal[0], pal[1], pal[2]))
        elif not sample.physical_link_up:
            pal = self._get_status_palette(HealthStatus.DEGRADED, False)
            self.lbl_wan_pill.setText("⚠ Kein Sync")
            self.lbl_wan_pill.setStyleSheet(self._get_pill_style(pal[0], pal[1], pal[2]))
        elif not sample.wan_connected:
            pal = self._get_status_palette(HealthStatus.DEGRADED, False)
            self.lbl_wan_pill.setText("⚠ Kein Internet")
            self.lbl_wan_pill.setStyleSheet(self._get_pill_style(pal[0], pal[1], pal[2]))
        else:
            pal = self._get_status_palette(HealthStatus.STABLE, True)
            self.lbl_wan_pill.setText("✓ WAN OK")
            self.lbl_wan_pill.setStyleSheet(self._get_pill_style(pal[0], pal[1], pal[2]))

    def _update_dns_pill(self, sample: TrafficSample) -> None:
        """Update text, colors and tooltip of the DNS status pill with dynamic IP threshold and HiDPI styling."""
        has_footer = self.config.show_session_totals
        has_wan = self.config.show_wan_status_pill
        base_w = 420 if has_footer else (270 if has_wan else 200)
        min_w = int(round(base_w * self.config.ui_scale))

        stable_pal = self._get_status_palette(HealthStatus.STABLE, True)
        warn_pal = self._get_status_palette(HealthStatus.DEGRADED, True)
        err_pal = self._get_status_palette(HealthStatus.DNS_ERROR, True)

        if (
            self.config.enable_internet_health
            and self.config.health_uncached_dns
            and sample.health.dns_ok is not None
        ):
            h = sample.health
            dns_ip_label = (
                f"({h.dns_ip}): "
                if (self.width() >= min_w and h.dns_ip)
                else ": "
            )
            if h.dns_ok is False:
                err_short = _format_dns_error(h.dns_error)
                if h.dns_error == "no_dns_server" or not h.dns_ip:
                    self.lbl_dns_pill.setText("✕ DNS: n/a")
                    self.lbl_dns_pill.setToolTip("Kein aktiver DNS-Server erkannt")
                else:
                    self.lbl_dns_pill.setText(f"✕ DNS: {err_short}")
                    https_note = (
                        "\nInternet per IP erreichbar → Lokaler DNS/AdGuard prüfen!"
                        if (h.ipv4_ok or h.ipv6_ok)
                        else ""
                    )
                    self.lbl_dns_pill.setToolTip(
                        f"Aktiver OS-DNS (Uncached): {h.dns_ip}\nStatus: {err_short}{https_note}"
                    )
                self.lbl_dns_pill.setStyleSheet(
                    self._get_pill_style(err_pal[0], err_pal[1], err_pal[2])
                )
                return

            if h.dns_ms is not None:
                ms_str = f"{h.dns_ms:.1f} ms".replace(".", ",")
                if h.dns_ms > 200.0:
                    self.lbl_dns_pill.setText(f"⚠ DNS{dns_ip_label}{ms_str}")
                    self.lbl_dns_pill.setStyleSheet(
                        self._get_pill_style(err_pal[0], err_pal[1], err_pal[2])
                    )
                elif h.dns_ms > 100.0:
                    self.lbl_dns_pill.setText(f"⚠ DNS{dns_ip_label}{ms_str}")
                    self.lbl_dns_pill.setStyleSheet(
                        self._get_pill_style(warn_pal[0], warn_pal[1], warn_pal[2])
                    )
                else:
                    self.lbl_dns_pill.setText(f"✓ DNS{dns_ip_label}{ms_str}")
                    self.lbl_dns_pill.setStyleSheet(
                        self._get_pill_style(stable_pal[0], stable_pal[1], stable_pal[2])
                    )
                self.lbl_dns_pill.setToolTip(
                    f"Aktiver OS-DNS: {h.dns_ip}\nUncached-Antwortzeit: {ms_str} (Cache umgangen)"
                )
                return

        if sample.dns_ms is not None:
            dns_ip_label = (
                f"({sample.active_dns_ip}): "
                if (self.width() >= min_w and sample.active_dns_ip)
                else ": "
            )
            ms_str = f"{sample.dns_ms:.1f} ms".replace(".", ",")
            if sample.dns_ms > 100.0:
                self.lbl_dns_pill.setText(f"⚠ DNS{dns_ip_label}{ms_str}")
                self.lbl_dns_pill.setStyleSheet(
                    self._get_pill_style(warn_pal[0], warn_pal[1], warn_pal[2])
                )
            else:
                self.lbl_dns_pill.setText(f"✓ DNS{dns_ip_label}{ms_str}")
                self.lbl_dns_pill.setStyleSheet(
                    self._get_pill_style(stable_pal[0], stable_pal[1], stable_pal[2])
                )
            if sample.active_dns_ip:
                self.lbl_dns_pill.setToolTip(f"Aktiver OS-DNS: {sample.active_dns_ip}\nAntwortzeit: {ms_str}")
        elif sample.active_dns_ip:
            self.lbl_dns_pill.setText("⚠ DNS: Timeout")
            self.lbl_dns_pill.setToolTip(f"Aktiver OS-DNS: {sample.active_dns_ip} (Keine Antwort)")
            self.lbl_dns_pill.setStyleSheet(
                self._get_pill_style(warn_pal[0], warn_pal[1], warn_pal[2])
            )
        else:
            self.lbl_dns_pill.setText("✕ DNS: n/a")
            self.lbl_dns_pill.setToolTip("Kein aktiver DNS-Server erkannt")
            self.lbl_dns_pill.setStyleSheet(
                self._get_pill_style("rgba(255, 255, 255, 0.4)", "rgba(255, 255, 255, 0.05)", "rgba(255, 255, 255, 0.15)", is_bold=False)
            )

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
            
            # Responsive abbreviation depending on width & visible pills
            has_pills = self.config.show_wan_status_pill or self.config.enable_dns_monitor
            if self.width() < 340 and has_pills:
                return f"{label}: Σ {tot_str}"
            if self.width() < 430 and has_pills:
                return f"{label}: ↓ {rx_str} • ↑ {tx_str}"
            return f"{label}: ↓ {rx_str} • ↑ {tx_str} (Σ {tot_str})"

        rx_str = format_bytes(sample.session_bytes_received)
        tx_str = format_bytes(sample.session_bytes_sent)
        if self.width() < 380 and (self.config.show_wan_status_pill or self.config.enable_dns_monitor):
            return f"Session: ↓ {rx_str} • ↑ {tx_str}"
        return f"Seit Widget-Start: ↓ {rx_str} • ↑ {tx_str}"

    def _update_tooltip(
        self, sample: TrafficSample, down_pct: float, up_pct: float
    ) -> None:
        bits = self.config.show_as_bits
        down_str = format_rate(sample.download_bps, bits)
        up_str = format_rate(sample.upload_bps, bits)

        target_label = "Lokal-Fallback" if sample.is_local_fallback else self.config.fritzbox_host
        tray_tip = (
            f"TrafficBox ({target_label})\n"
            f"↓ Down: {down_str} ({down_pct:.1f}%)\n"
            f"↑ Up: {up_str} ({up_pct:.1f}%)"
        ).replace(".", ",")
        if self.config.enable_internet_health and sample.health.status != HealthStatus.UNKNOWN:
            h = sample.health
            if h.status == HealthStatus.STABLE:
                tray_tip += "\nStatus: Stabil"
            elif h.reason:
                tray_tip += f"\nStatus: {h.short_tag} – {h.reason}"
            else:
                tray_tip += f"\nStatus: {h.short_tag}"
        self.tray_icon.setToolTip(tray_tip)

        if not self.config.show_connection_tooltip:
            self.lbl_icon.setToolTip("")
            self.lbl_title.setToolTip("")
            self.lbl_wan_pill.setToolTip("")
            self.setToolTip("")
            return

        max_down_bps, max_up_bps = self._effective_max_bandwidths(sample)
        max_down_mbps = (max_down_bps * 8.0) / 1_000_000.0
        max_up_mbps = (max_up_bps * 8.0) / 1_000_000.0

        if sample.is_local_fallback:
            lines = [
                "<b>Lokaler Netzwerk-Traffic (Fallback)</b>",
                "Status: <b>Keine FRITZ!Box erreichbar</b> – zeige lokalen Adapter-Traffic",
                f"Skalierung: ↓ {max_down_mbps:.1f} Mbit/s • ↑ {max_up_mbps:.1f} Mbit/s".replace(
                    ".", ","
                ),
                f"Seit Widget-Start: ↓ {format_bytes(sample.session_bytes_received)} • ↑ {format_bytes(sample.session_bytes_sent)}",
            ]
        else:
            box_title = html.escape(sample.box_name or f"Fritz!Box ({self.config.fritzbox_host})")
            conn_status = html.escape(sample.connection_status)
            ext_ip = html.escape(sample.external_ip)
            lines = [
                f"<b>{box_title}</b>",
                f"Status: <b>{conn_status}</b> • Verbunden seit: {format_uptime(sample.uptime_seconds)}",
                f"Externe IP: <code>{ext_ip}</code>",
                f"Leitungskapazität: ↓ {max_down_mbps:.1f} Mbit/s • ↑ {max_up_mbps:.1f} Mbit/s".replace(
                    ".", ","
                ),
                f"Seit Widget-Start: ↓ {format_bytes(sample.session_bytes_received)} • ↑ {format_bytes(sample.session_bytes_sent)}",
            ]

        if sample.is_foreign_box:
            lines.append("<span style='color:#00E5FF;'>ℹ Fremde FRITZ!Box – Login zum Schutz vor Sperrung pausiert</span>")

        if sample.total_bytes_received > 0 or sample.total_bytes_sent > 0:
            lines.append(
                f"Seit Verbindung: ↓ {format_bytes(sample.total_bytes_received)} • ↑ {format_bytes(sample.total_bytes_sent)}"
            )

        if sample.error_message:
            lines.append(f"<span style='color:#FF5252;'>Fehler: {html.escape(sample.error_message)}</span>")

        router_tip_html = "<br>".join(lines)
        self.lbl_icon.setToolTip(router_tip_html)
        self.lbl_title.setToolTip(router_tip_html)
        self.setToolTip("")

        if self.config.enable_internet_health and sample.health.status != HealthStatus.UNKNOWN:
            h = sample.health
            status_col = self._get_status_palette(h.status, sample.is_connected)[0]
            status_names = {
                HealthStatus.STABLE: "Stabil",
                HealthStatus.DEGRADED: "Eingeschränkt",
                HealthStatus.DNS_ERROR: "DNS-Störung",
                HealthStatus.ZOMBIE_WAN: "Kein Internet (Router verbunden)",
                HealthStatus.OFFLINE: "Offline",
                HealthStatus.LAN_ERROR: "LAN-Problem",
            }
            s_name = status_names.get(h.status, "Unbekannt")
            sat_badge = (
                " <span style='color:#94A3B8;'>(Leitung ausgelastet)</span>"
                if (h.is_line_saturated and h.status == HealthStatus.DEGRADED)
                else ""
            )
            health_lines = [
                f"<b>Internet:</b> <span style='color:{status_col};'><b>{html.escape(s_name)}</b></span>{sat_badge}"
            ]

            if h.status != HealthStatus.STABLE and h.reason:
                reason_clean = (
                    h.reason.replace(" (Leitung ausgelastet)", "")
                    if (h.is_line_saturated and h.status == HealthStatus.DEGRADED)
                    else h.reason
                )
                if reason_clean:
                    health_lines.append(html.escape(reason_clean))

            if h.status == HealthStatus.LAN_ERROR:
                gw_lbl = html.escape(h.gateway_ip or "-")
                lan_state = (
                    f"{h.lan_ping_ms:.1f} ms".replace(".", ",")
                    if h.lan_ping_ms is not None
                    else "nicht erreichbar"
                )
                if h.lan_loss_pct > 0:
                    lan_state += f" (Verlust {h.lan_loss_pct:.0f} %)"
                health_lines.append(f"LAN ({gw_lbl}): {html.escape(lan_state)}")
            elif h.status == HealthStatus.DNS_ERROR:
                d_ip = html.escape(h.dns_ip or "-")
                d_err = html.escape(_format_dns_error(h.dns_error))
                v4_ok, v4_tot = h.ipv4_quorum
                v4_txt = f"IPv4 {v4_ok}/{v4_tot}" if v4_tot > 0 else "IPv4 n/a"
                health_lines.append(f"DNS ({d_ip}): {d_err} • {html.escape(v4_txt)}")
            else:
                lan_rtt = (
                    f"{h.lan_ping_ms:.1f} ms".replace(".", ",")
                    if h.lan_ping_ms is not None
                    else "n/a"
                )
                v4_ok, v4_tot = h.ipv4_quorum
                if v4_tot > 0:
                    v4_rtt = f" ({h.ipv4_ms:.0f} ms)" if (h.ipv4_ok and h.ipv4_ms is not None) else ""
                    v4_txt = f"IPv4 {v4_ok}/{v4_tot}{v4_rtt}" if h.ipv4_ok else f"IPv4 ✕ 0/{v4_tot}"
                else:
                    v4_txt = "IPv4 n/a"

                v6_ok, v6_tot = h.ipv6_quorum
                if v6_tot > 0:
                    v6_rtt = f" ({h.ipv6_ms:.0f} ms)" if (h.ipv6_ok and h.ipv6_ms is not None) else ""
                    v6_txt = f"IPv6 {v6_ok}/{v6_tot}{v6_rtt}" if h.ipv6_ok else f"IPv6 ✕ 0/{v6_tot}"
                else:
                    v6_txt = "IPv6 n/a"
                health_lines.append(f"LAN: {lan_rtt} • {html.escape(v4_txt)} • {html.escape(v6_txt)}")

            if h.wan_p95_ms is not None or h.wan_loss_pct > 0:
                p95_s = f"{h.wan_p95_ms:.0f}" if h.wan_p95_ms is not None else "-"
                jit_s = f"{h.wan_jitter_ms:.1f}".replace(".", ",")
                loss_s = f"{h.wan_loss_pct:.0f} %"
                base_s = (
                    f" (Normalwert {h.baseline_rtt_ms:.0f})"
                    if (h.baseline_ready and h.baseline_rtt_ms is not None)
                    else ""
                )
                health_lines.append(f"Ping (15s): p85 {p95_s} ms{base_s} • Jitter {jit_s} ms • Loss {loss_s}")

            self.lbl_wan_pill.setToolTip("<br>".join(health_lines))
        else:
            self.lbl_wan_pill.setToolTip(router_tip_html)
