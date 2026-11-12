"""Main frameless floating TrafficBox Widget."""

from __future__ import annotations

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

from src.api.models import OnlineCounterStats, PeriodCounter, TrafficSample
from src.api.net_health import set_shutting_down
from src.api.worker import PollingWorker
from src.autostart import sync_kwin_position_rule
from src.config import AppConfig
from src.ui.formatters import format_bytes, format_rate, format_uptime
from src.ui.graph_canvas import SplitTrafficGraphWidget
from src.ui.icons import create_arrow_pixmap, create_ui_icon
from src.ui.online_counter_view import OnlineCounterView
from src.ui.settings_dlg import SettingsDialog
from src.ui.tray import create_router_icon


class VisualSizeGrip(QSizeGrip):
    """QSizeGrip with custom diagonal grip dots that remain visible across all desktop themes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("Größe anpassen (Ziehen)")

    def update_scale(self, scale: float) -> None:
        """Adjust physical grip area to match UI scaling factor."""
        sz = max(12, int(round(14.0 * scale)))
        self.setFixedSize(sz, sz)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        pen_shadow = QColor(0, 0, 0, 180)
        pen_fg = QColor(255, 255, 255, 140)
        # Classic 6-dot diagonal resize grip triangle (3 rows: 1, 2, 3 dots)
        scale = max(1.0, w / 14.0)
        base_dots = [
            (3, 3),
            (7, 3), (3, 7),
            (11, 3), (7, 7), (3, 11),
        ]
        dots = [(int(round(x * scale)), int(round(y * scale))) for x, y in base_dots]
        for dx, dy in dots:
            painter.setPen(pen_shadow)
            painter.drawPoint(w - dx + 1, h - dy + 1)
            painter.setPen(pen_fg)
            painter.drawPoint(w - dx, h - dy)
        painter.end()


class TrafficBox(QWidget):
    """Frameless, translucent cross-platform desktop widget for live Fritz!Box traffic."""

    request_poll = Signal()
    request_reset_session = Signal()
    request_reload_credentials = Signal()

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        set_shutting_down(False)
        self.config = config
        self._drag_start_pos: QPoint = QPoint()
        self._drag_offset: QPoint | None = None
        self._peak_down_bps: float = 0.0
        self._peak_up_bps: float = 0.0
        self._last_sample: TrafficSample = TrafficSample()
        self._settings_dlg: SettingsDialog | None = None
        self._in_layout_transition: bool = False
        self._is_quitting: bool = False
        self._was_compact: bool = self.config.compact_mode
        self._was_counters: bool = self.config.active_view == "counters"
        self._user_is_moving: bool = False
        self._last_drag_pos: QPoint | None = None

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

        self.lbl_wan_pill = QLabel("✓ WAN OK")
        self.lbl_wan_pill.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        self.lbl_wan_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_footer = QLabel("Heute: 0 B")
        self.lbl_footer.setFont(QFont("Segoe UI", 7))
        self.lbl_footer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.footer_spacer = QWidget(self)
        self.footer_spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.lbl_dns_pill = QLabel("✓ DNS")
        self.lbl_dns_pill.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        self.lbl_dns_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)

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

        footer_css = (
            f"color: {self.config.title_color}; "
            "background-color: rgba(255, 255, 255, 12); "
            "border: 1px solid rgba(255, 255, 255, 24); "
            "border-radius: 9px; padding: 1px 7px;"
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

    def _get_pill_style(self, text_col: str, bg_col: str, border_col: str, is_bold: bool = True) -> str:
        """Return responsive stylesheet for footer status pills (WAN/DNS) scaled to HiDPI."""
        base_scale = self.config.ui_scale
        radius = max(6, int(round(9.0 * base_scale)))
        pad_v = max(1, int(round(1.5 * base_scale)))
        pad_h = max(4, int(round(7.0 * base_scale)))
        bold_css = " font-weight: bold;" if is_bold else ""
        return (
            f"color: {text_col}; background-color: {bg_col}; "
            f"border: 1px solid {border_col}; border-radius: {radius}px; "
            f"padding: {pad_v}px {pad_h}px;{bold_css}"
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
        self.lbl_icon.setPixmap(create_router_icon(is_conn).pixmap(QSize(hdr_icon_sz, hdr_icon_sz)))
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

        btn_icon_sz = max(11, int(round(13.0 * base_scale)))
        btn_h = max(18, int(round(20.0 * base_scale)))
        btn_font_px = max(8, int(round(9.0 * base_scale)))
        btn_radius = max(3, int(round(4.0 * base_scale)))
        pad_v = max(1, int(round(1.0 * base_scale)))
        pad_h = max(4, int(round(6.0 * base_scale)))
        settings_sz = max(18, int(round(20.0 * base_scale)))

        self.btn_view_graph.setFixedHeight(btn_h)
        self.btn_view_counters.setFixedHeight(btn_h)
        self.btn_settings.setFixedSize(settings_sz, settings_sz)

        self.btn_view_graph.setIcon(create_ui_icon("graph", graph_icon_col, btn_icon_sz))
        self.btn_view_counters.setIcon(create_ui_icon("counters", counters_icon_col, btn_icon_sz))
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

        if not sample.box_reachable:
            self.lbl_down_rate.setText("Offline")
            self.lbl_up_rate.setText("Offline")
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
        self.lbl_icon.setPixmap(create_router_icon(sample.is_connected).pixmap(QSize(hdr_icon_sz, hdr_icon_sz)))

        self.graph_widget.push_sample(
            sample.download_bps if sample.is_connected else 0.0,
            sample.upload_bps if sample.is_connected else 0.0,
            sample.guest_download_bps if sample.is_connected else 0.0,
            sample.guest_upload_bps if sample.is_connected else 0.0,
            sample.max_download_bps,
            sample.max_upload_bps,
            ping_ms=sample.ping_ms,
            jitter_ms=sample.jitter_ms,
            pc_down_bps=sample.local_pc_download_bps if sample.is_connected else 0.0,
            pc_up_bps=sample.local_pc_upload_bps if sample.is_connected else 0.0,
        )

        # Rolling peak across the visible graph window (auto-resets as spikes scroll out)
        self._peak_down_bps = self.graph_widget.current_peak_down_bps
        self._peak_up_bps = self.graph_widget.current_peak_up_bps

        down_pct, up_pct = self._update_live_rate_displays(sample)

        bits = self.config.show_as_bits

        # Local PC readout (if enabled & active & allowed in header)
        if (
            self.config.enable_local_traffic_monitor
            and self.config.show_local_traffic_in_header
            and sample.local_pc_active
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

        self._update_tooltip(sample, down_pct, up_pct)

    def _update_wan_status_pill(self, sample: TrafficSample) -> None:
        """Update text, colors and tooltip of the WAN status pill with HiDPI styling."""
        if not sample.box_reachable:
            self.lbl_wan_pill.setText("✕ Box Offline")
            self.lbl_wan_pill.setStyleSheet(
                self._get_pill_style("#FF5252", "rgba(255, 82, 82, 0.16)", "rgba(255, 82, 82, 0.45)")
            )
        elif not sample.physical_link_up:
            self.lbl_wan_pill.setText("⚠ Kein Sync")
            self.lbl_wan_pill.setStyleSheet(
                self._get_pill_style("#FFAB00", "rgba(255, 171, 0, 0.16)", "rgba(255, 171, 0, 0.45)")
            )
        elif not sample.wan_connected:
            self.lbl_wan_pill.setText("⚠ Kein Internet")
            self.lbl_wan_pill.setStyleSheet(
                self._get_pill_style("#FFAB00", "rgba(255, 171, 0, 0.16)", "rgba(255, 171, 0, 0.45)")
            )
        else:
            self.lbl_wan_pill.setText("✓ WAN OK")
            self.lbl_wan_pill.setStyleSheet(
                self._get_pill_style("#00E5FF", "rgba(0, 229, 255, 0.10)", "rgba(0, 229, 255, 0.35)")
            )

    def _update_dns_pill(self, sample: TrafficSample) -> None:
        """Update text, colors and tooltip of the DNS status pill with dynamic IP threshold and HiDPI styling."""
        if sample.dns_ms is not None:
            # Dynamic threshold: 270px without middle counter, 420px with middle counter scaled to UI factor
            has_footer = self.config.show_session_totals
            has_wan = self.config.show_wan_status_pill
            base_w = 420 if has_footer else (270 if has_wan else 200)
            min_w = int(round(base_w * self.config.ui_scale))

            dns_ip_label = (
                f"({sample.active_dns_ip}): "
                if (self.width() >= min_w and sample.active_dns_ip)
                else ": "
            )
            ms_str = f"{sample.dns_ms:.1f} ms".replace(".", ",")
            if sample.dns_ms > 80.0:
                self.lbl_dns_pill.setText(f"⚠ DNS{dns_ip_label}{ms_str}")
                self.lbl_dns_pill.setStyleSheet(
                    self._get_pill_style("#FFAB00", "rgba(255, 171, 0, 0.16)", "rgba(255, 171, 0, 0.45)")
                )
            else:
                self.lbl_dns_pill.setText(f"✓ DNS{dns_ip_label}{ms_str}")
                self.lbl_dns_pill.setStyleSheet(
                    self._get_pill_style("#00E5FF", "rgba(0, 229, 255, 0.10)", "rgba(0, 229, 255, 0.35)")
                )
            if sample.active_dns_ip:
                self.lbl_dns_pill.setToolTip(f"Aktiver OS-DNS: {sample.active_dns_ip}\nAntwortzeit: {ms_str}")
        elif sample.active_dns_ip:
            self.lbl_dns_pill.setText("⚠ DNS: Timeout")
            self.lbl_dns_pill.setToolTip(f"Aktiver OS-DNS: {sample.active_dns_ip} (Keine Antwort)")
            self.lbl_dns_pill.setStyleSheet(
                self._get_pill_style("#FFAB00", "rgba(255, 171, 0, 0.16)", "rgba(255, 171, 0, 0.45)")
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

        tray_tip = (
            f"TrafficBox ({self.config.fritzbox_host})\n"
            f"↓ Down: {down_str} ({down_pct:.1f}%)\n"
            f"↑ Up: {up_str} ({up_pct:.1f}%)"
        ).replace(".", ",")
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

        box_title = sample.box_name or f"Fritz!Box ({self.config.fritzbox_host})"
        lines = [
            f"<b>{box_title}</b>",
            f"Status: <b>{sample.connection_status}</b> • Verbunden seit: {format_uptime(sample.uptime_seconds)}",
            f"Externe IP: <code>{sample.external_ip}</code>",
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
            lines.append(f"<span style='color:#FF5252;'>Fehler: {sample.error_message}</span>")

        tip_html = "<br>".join(lines)
        self.lbl_icon.setToolTip(tip_html)
        self.lbl_title.setToolTip(tip_html)
        self.lbl_wan_pill.setToolTip(tip_html)
        self.setToolTip("")

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
            self._drag_start_pos = event.globalPosition().toPoint()
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._user_is_moving = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and not self.config.locked_pos
        ):
            delta = (event.globalPosition().toPoint() - self._drag_start_pos).manhattanLength()
            if delta >= 3:
                self._user_is_moving = True
                app = QApplication.instance()
                if app is not None and app.platformName() == "wayland":
                    handle = self.windowHandle()
                    if handle is not None and hasattr(handle, "startSystemMove"):
                        if handle.startSystemMove():
                            self._drag_offset = None
                            event.accept()
                            return
                new_pos = event.globalPosition().toPoint() - self._drag_offset
                if self.config.snap_to_edges:
                    new_pos = self._snap_position(new_pos)
                self._last_drag_pos = new_pos
                self.move(new_pos)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def _snap_position(self, pos: QPoint, snap_dist: int = 14) -> QPoint:
        """Snap widget position magnetically to the available screen edges."""
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        center = QPoint(x + w // 2, y + h // 2)
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()

        if screen is None:
            return pos

        avail = screen.availableGeometry()
        left_edge = avail.x()
        right_edge = avail.x() + avail.width() - w
        top_edge = avail.y()
        bottom_edge = avail.y() + avail.height() - h

        candidates_x: list[tuple[int, int]] = []
        candidates_y: list[tuple[int, int]] = []

        for edge_x in (left_edge, right_edge):
            d = abs(x - edge_x)
            if d <= snap_dist:
                candidates_x.append((d, edge_x))
        for edge_y in (top_edge, bottom_edge):
            d = abs(y - edge_y)
            if d <= snap_dist:
                candidates_y.append((d, edge_y))

        if candidates_x:
            x = min(candidates_x, key=lambda item: item[0])[1]
        if candidates_y:
            y = min(candidates_y, key=lambda item: item[0])[1]
        return QPoint(x, y)

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        if not self._in_layout_transition and self.isVisible() and self._user_is_moving:
            p = event.pos()
            self.config.pos_x = p.x()
            self.config.pos_y = p.y()
            if hasattr(self, "_save_pos_timer"):
                self._save_pos_timer.start(500)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            if self._user_is_moving:
                pos = self._last_drag_pos if self._last_drag_pos is not None else self.pos()
                self.config.pos_x = pos.x()
                self.config.pos_y = pos.y()
                self._last_drag_pos = None
                if not self.config.compact_mode:
                    self.config.widget_width = self.width()
                    self.config.widget_height = self.height()
                self.config.save()
                if sys.platform == "linux":
                    sync_kwin_position_rule(self.config.pos_x, self.config.pos_y)
                self._user_is_moving = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._apply_x11_skip_taskbar()

    def _apply_x11_skip_taskbar(self) -> None:
        """Ensure _NET_WM_STATE_SKIP_TASKBAR is set on X11 / XWayland surfaces to hide from taskbars."""
        if sys.platform.startswith("linux"):
            wid = self.winId()
            if wid:
                import shutil
                import subprocess

                xprop_bin = shutil.which("xprop")
                if xprop_bin:
                    try:
                        subprocess.run(
                            [
                                xprop_bin,
                                "-id",
                                str(int(wid)),
                                "-f",
                                "_NET_WM_STATE",
                                "32a",
                                "-set",
                                "_NET_WM_STATE",
                                "_NET_WM_STATE_SKIP_TASKBAR, _NET_WM_STATE_SKIP_PAGER",
                            ],
                            check=False,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=0.5,
                        )
                    except Exception:
                        pass

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self._update_dynamic_scaling()
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
        menu.exec(self.mapToGlobal(event.pos()))

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
        footer_menu_title = (
            "Footer-Zähler (Zeitraum)"
            if self.config.show_session_totals
            else "Footer-Zähler (Deaktiviert)"
        )
        footer_menu = menu.addMenu(footer_menu_title)
        footer_group = QActionGroup(self)

        act_f_off = QAction("Ausblenden (deaktiviert)", self, checkable=True)
        act_f_off.setChecked(not self.config.show_session_totals)
        act_f_off.triggered.connect(lambda _chk=False: self._toggle_footer_counter(False))
        footer_group.addAction(act_f_off)
        footer_menu.addAction(act_f_off)
        footer_menu.addSeparator()

        for f_label, f_key in [
            ("Heute (Online-Zähler)", "today"),
            ("Gestern (Online-Zähler)", "yesterday"),
            ("Aktuelle Woche (Online-Zähler)", "week"),
            ("Aktueller Monat (Online-Zähler)", "month"),
            ("Vormonat (Online-Zähler)", "last_month"),
            ("Seit Widget-Start (ohne Login)", "session"),
        ]:
            act_f = QAction(f_label, self, checkable=True)
            act_f.setChecked(
                self.config.show_session_totals and self.config.footer_counter_mode == f_key
            )
            act_f.triggered.connect(lambda _chk=False, k=f_key: self._set_footer_mode(k))
            footer_group.addAction(act_f)
            footer_menu.addAction(act_f)

        act_footer = QAction("Footer-Zähler anzeigen", self, checkable=True)
        act_footer.setChecked(self.config.show_session_totals)
        act_footer.triggered.connect(self._toggle_footer_counter)
        menu.addAction(act_footer)

        act_bits = QAction("Als Bit/s anzeigen (Mbit/s)", self, checkable=True)
        act_bits.setChecked(self.config.show_as_bits)
        act_bits.triggered.connect(self._toggle_bits)
        menu.addAction(act_bits)

        act_compact = QAction("Kompakt-Modus (nur Zahlen)", self, checkable=True)
        act_compact.setChecked(self.config.compact_mode)
        act_compact.triggered.connect(self._toggle_compact)
        menu.addAction(act_compact)

        act_graph_only = QAction("Nur-Graph-Modus (Zahlen ausblenden)", self, checkable=True)
        act_graph_only.setChecked(self.config.graph_only_mode)
        act_graph_only.triggered.connect(self._toggle_graph_only)
        menu.addAction(act_graph_only)

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
        act_reset_session.setEnabled(self.config.show_session_totals)
        act_reset_session.triggered.connect(self._reset_session_counter)
        menu.addAction(act_reset_session)

        act_hide = QAction(
            "Widget ausblenden" if self.isVisible() else "Widget einblenden", self
        )
        act_hide.triggered.connect(self._toggle_visibility)
        menu.addAction(act_hide)

        menu.addSeparator()

        act_about = QAction("Über TrafficBox...", self)
        act_about.triggered.connect(lambda: self.open_settings_dialog(5))
        menu.addAction(act_about)

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
        self.config.show_session_totals = True
        self.config.save()
        self._apply_config_visuals()
        if self._last_sample:
            self._on_sample_received(self._last_sample)

    def _toggle_footer_counter(self, checked: bool) -> None:
        self.config.show_session_totals = checked
        self.config.save()
        self._apply_config_visuals()
        if self._last_sample:
            self._on_sample_received(self._last_sample)

    def _toggle_bits(self, checked: bool) -> None:
        self.config.show_as_bits = checked
        self.config.save()
        self._on_sample_received(self._last_sample)

    def _toggle_compact(self, checked: bool) -> None:
        self.config.compact_mode = checked
        if checked:
            self.config.graph_only_mode = False
        self.config.save()
        self._apply_config_visuals()

    def _toggle_graph_only(self, checked: bool) -> None:
        self.config.graph_only_mode = checked
        if checked:
            self.config.compact_mode = False
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

    def open_settings_dialog(self, initial_tab: int = 0) -> None:
        """Open or focus the Settings dialog, optionally switching to a specific tab."""
        tab_idx = (
            initial_tab
            if isinstance(initial_tab, int) and not isinstance(initial_tab, bool)
            else 0
        )
        if self._settings_dlg is not None and self._settings_dlg.isVisible():
            if 0 <= tab_idx < self._settings_dlg.tabs.count():
                self._settings_dlg.tabs.setCurrentIndex(tab_idx)
            self._settings_dlg.raise_()
            self._settings_dlg.activateWindow()
            return

        self._settings_dlg = SettingsDialog(
            self.config,
            on_apply=self._on_settings_applied,
            parent=None,
            initial_tab=tab_idx,
        )
        self._settings_dlg.show()
        self._settings_dlg.raise_()
        self._settings_dlg.activateWindow()

    def _on_settings_applied(self) -> None:
        self._apply_config_visuals()
        self.request_reload_credentials.emit()
        self.request_poll.emit()

    def _stop_background_tasks(self, save_state: bool = True) -> None:
        """Immediately halt polling timer and worker thread (safe to call multiple times)."""
        if self._is_quitting:
            return
        self._is_quitting = True
        self._save_pos_timer.stop()
        self._poll_timer.stop()
        self._worker.stop()

        if save_state:
            self.config.pos_x = self.x()
            self.config.pos_y = self.y()
            if not self.config.compact_mode:
                self.config.widget_width = self.width()
                self.config.widget_height = self.height()
            self.config.save()
            if sys.platform == "linux":
                sync_kwin_position_rule(self.config.pos_x, self.config.pos_y)

        if self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait(1200)
        self.tray_icon.hide()

    def _on_commit_data_request(self, _manager: object) -> None:
        """Stop background polling immediately when Windows/Linux session shuts down."""
        self._stop_background_tasks(save_state=True)

    def _on_app_about_to_quit(self) -> None:
        """Ensure worker thread is stopped when QApplication exits."""
        self._stop_background_tasks(save_state=True)

    def quit_application(self) -> None:
        """Cleanly stop worker thread, save position, and exit."""
        self._stop_background_tasks(save_state=True)
        QApplication.quit()
