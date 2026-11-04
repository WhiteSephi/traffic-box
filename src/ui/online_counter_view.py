"""Responsive in-widget card view for the Fritz!Box Online-Zähler (Variant 2)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.api.models import OnlineCounterStats, TrafficSample
from src.config import AppConfig
from src.ui.formatters import format_bytes, format_uptime
from src.ui.icons import create_arrow_pixmap


class RatioBar(QWidget):
    """Slim, elegant horizontal dual-color bar (Download left, Upload right)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.down_bytes: int = 0
        self.up_bytes: int = 0
        self.down_color: QColor = QColor("#FFEA00")
        self.up_color: QColor = QColor("#6B8AFF")
        self.setFixedHeight(4)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_data(
        self,
        down_bytes: int,
        up_bytes: int,
        down_color: str,
        up_color: str,
    ) -> None:
        self.down_bytes = max(0, down_bytes)
        self.up_bytes = max(0, up_bytes)
        self.down_color = QColor(down_color)
        self.up_color = QColor(up_color)
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())
        radius = min(3.5, h / 2.0)
        rect = QRectF(0.0, 0.0, w, h)

        # Track background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 20))
        painter.drawRoundedRect(rect, radius, radius)

        total = self.down_bytes + self.up_bytes
        if total <= 0:
            return

        down_ratio = self.down_bytes / float(total)
        down_w = w * down_ratio
        up_w = w - down_w

        painter.save()
        painter.setClipRect(rect)
        if down_w > 0.5:
            painter.setBrush(self.down_color)
            painter.drawRoundedRect(QRectF(0.0, 0.0, down_w, h), radius, radius)
        if up_w > 0.5:
            painter.setBrush(self.up_color)
            painter.drawRoundedRect(QRectF(down_w, 0.0, up_w, h), radius, radius)
        painter.restore()


class PeriodCardWidget(QWidget):
    """Two-tiered card row displaying a time period, total volume, ratio bar, and Down/Up volumes with vector arrow icons."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scale: float = 1.0
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(2)

        # 1. Top row: Period label (left) & Total volume (right)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(4)

        self.lbl_period = QLabel("")
        self.lbl_period.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))

        self.lbl_total = QLabel("")
        self.lbl_total.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.lbl_total.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        top_row.addWidget(self.lbl_period)
        top_row.addStretch(1)
        top_row.addWidget(self.lbl_total)
        layout.addLayout(top_row)

        # 2. Middle: Full-width dual-color ratio bar
        self.bar = RatioBar(self)
        layout.addWidget(self.bar)

        # 3. Bottom row: Download (left) with vector icon & Upload (right) with vector icon
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(4)

        self.icon_down = QLabel()
        self.icon_down.setFixedSize(10, 10)
        self.lbl_down = QLabel("")
        self.lbl_down.setFont(QFont("Segoe UI", 8))

        self.icon_up = QLabel()
        self.icon_up.setFixedSize(10, 10)
        self.lbl_up = QLabel("")
        self.lbl_up.setFont(QFont("Segoe UI", 8))
        self.lbl_up.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        bottom_row.addWidget(self.icon_down)
        bottom_row.addWidget(self.lbl_down)
        bottom_row.addStretch(1)
        bottom_row.addWidget(self.icon_up)
        bottom_row.addWidget(self.lbl_up)
        layout.addLayout(bottom_row)

    def set_scale(self, scale: float, config: AppConfig) -> None:
        """Dynamically scale fonts, bar height, and icon sizes."""
        self._scale = scale

        title_pt = max(8, min(12, int(round(9.0 * scale))))
        self.lbl_period.setFont(QFont("Segoe UI", title_pt, QFont.Weight.DemiBold))
        self.lbl_total.setFont(QFont("Segoe UI", title_pt, QFont.Weight.Bold))

        bar_h = max(3, min(7, int(round(4.0 * scale))))
        self.bar.setFixedHeight(bar_h)

        sub_pt = max(7, min(10, int(round(8.0 * scale))))
        self.lbl_down.setFont(QFont("Segoe UI", sub_pt))
        self.lbl_up.setFont(QFont("Segoe UI", sub_pt))

        icon_sz = max(9, min(14, int(round(10.0 * scale))))
        self.icon_down.setFixedSize(icon_sz, icon_sz)
        self.icon_up.setFixedSize(icon_sz, icon_sz)

        if self.icon_down.isVisible():
            self.icon_down.setPixmap(create_arrow_pixmap(config.download_color, "down", icon_sz))
            self.icon_up.setPixmap(create_arrow_pixmap(config.upload_color, "up", icon_sz))

    def set_data(
        self,
        period_name: str,
        total_str: str,
        down_str: str,
        up_str: str,
        down_bytes: int,
        up_bytes: int,
        config: AppConfig,
    ) -> None:
        self.lbl_period.setText(period_name)
        self.lbl_period.setStyleSheet(f"color: {config.title_color};")

        self.lbl_total.setText(
            f"Gesamt: {total_str}"
            if total_str and "Login" not in total_str
            else total_str
        )
        self.lbl_total.setStyleSheet("color: #FFFFFF;")

        self.lbl_down.setText(down_str)
        self.lbl_down.setStyleSheet(f"color: {config.download_color};")
        self.lbl_up.setText(up_str)
        self.lbl_up.setStyleSheet(f"color: {config.upload_color};")

        # Icons
        has_data = (down_bytes + up_bytes) > 0 or (
            down_str != "-" and "Login" not in total_str
        )
        if has_data:
            icon_sz = max(9, min(14, int(round(10.0 * self._scale))))
            self.icon_down.setPixmap(
                create_arrow_pixmap(config.download_color, "down", icon_sz)
            )
            self.icon_down.setVisible(True)
            self.icon_up.setPixmap(create_arrow_pixmap(config.upload_color, "up", icon_sz))
            self.icon_up.setVisible(True)
        else:
            self.icon_down.setVisible(False)
            self.icon_up.setVisible(False)

        self.bar.set_data(
            down_bytes=down_bytes,
            up_bytes=up_bytes,
            down_color=config.download_color,
            up_color=config.upload_color,
        )


class OnlineCounterView(QWidget):
    """Responsive in-widget card view showing Fritz!Box Online-Zähler stats."""

    def __init__(
        self,
        config: AppConfig,
        on_open_settings: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.on_open_settings = on_open_settings
        self._scale: float = 1.0
        self.setMinimumHeight(145)

        self._build_ui()
        self.apply_theme()

    def _build_ui(self) -> None:
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(4, 2, 4, 2)
        self.root_layout.setSpacing(4)

        self.cards_container = QWidget(self)
        self.cards_container.setObjectName("cards_container")
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(6, 3, 6, 3)
        self.cards_layout.setSpacing(3)

        # 5 Reusable card rows
        self.cards: list[PeriodCardWidget] = []
        for _ in range(5):
            card = PeriodCardWidget(self.cards_container)
            self.cards.append(card)
            self.cards_layout.addWidget(card, 1)

        self.root_layout.addWidget(self.cards_container, 1)

        # Login hint button
        self.btn_login_hint = QPushButton(
            "🔒 Fritz!OS Login in Einstellungen aktivieren für Heute / Woche / Monat"
        )
        self.btn_login_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_login_hint.clicked.connect(self.on_open_settings)
        self.btn_login_hint.setVisible(False)
        self.root_layout.addWidget(self.btn_login_hint)

    def set_scale(self, scale: float) -> None:
        """Apply dynamic scale to all period cards."""
        self._scale = scale
        for card in self.cards:
            card.set_scale(scale, self.config)

    def apply_theme(self) -> None:
        """Apply current AppConfig colors and background styles."""
        bg = QColor(self.config.background_color).darker(118).name()
        border = self.config.border_color
        hdr_bg = QColor(self.config.background_color).lighter(125).name()
        alt_bg = QColor(self.config.background_color).lighter(112).name()

        self.cards_container.setStyleSheet(
            f"""
            QWidget#cards_container {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
            """
        )

        self.btn_login_hint.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {hdr_bg};
                color: {self.config.download_color};
                border: 1px dashed {border};
                border-radius: 4px;
                padding: 4px 8px;
                font-family: 'Segoe UI';
                font-size: 10px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {alt_bg};
            }}
            """
        )

    def update_from_sample(self, sample: TrafficSample) -> None:
        """Populate the 5 cards with Online-Zähler stats or UPnP fallback counters."""
        oc: OnlineCounterStats = sample.online_counters
        if oc.is_available:
            self.btn_login_hint.setVisible(False)
            rows = [
                ("Heute", oc.today),
                ("Gestern", oc.yesterday),
                ("Aktuelle Woche", oc.this_week),
                ("Aktueller Monat", oc.this_month),
                ("Vormonat", oc.last_month),
            ]
            for idx, (label, cnt) in enumerate(rows):
                self.cards[idx].set_data(
                    period_name=label,
                    total_str=format_bytes(cnt.total_bytes),
                    down_str=format_bytes(cnt.received_bytes),
                    up_str=format_bytes(cnt.sent_bytes),
                    down_bytes=cnt.received_bytes,
                    up_bytes=cnt.sent_bytes,
                    config=self.config,
                )
        else:
            self.btn_login_hint.setVisible(True)
            if sample.is_foreign_box:
                box_display = sample.box_name or "Andere Box"
                self.btn_login_hint.setText(f"ℹ Fremde Box ({box_display}) – Login zum Schutz vor Sperrung pausiert")
                self.btn_login_hint.setStyleSheet(
                    "QPushButton { background-color: rgba(0, 229, 255, 0.16); color: #00E5FF; "
                    "border: 1px solid rgba(0, 229, 255, 0.45); border-radius: 4px; padding: 4px 8px; "
                    "font-family: 'Segoe UI'; font-size: 9.5px; font-weight: bold; }"
                    "QPushButton:hover { background-color: rgba(0, 229, 255, 0.28); }"
                )
            elif self.config.enable_guest_monitor:
                self.btn_login_hint.setText("⚠ Fritz!OS Login fehlgeschlagen (Passwort in ⚙ Einstellungen prüfen)")
                self.btn_login_hint.setStyleSheet(
                    "QPushButton { background-color: rgba(255, 82, 82, 0.16); color: #FF5252; "
                    "border: 1px solid rgba(255, 82, 82, 0.45); border-radius: 4px; padding: 4px 8px; "
                    "font-family: 'Segoe UI'; font-size: 9.5px; font-weight: bold; }"
                    "QPushButton:hover { background-color: rgba(255, 82, 82, 0.28); }"
                )
            else:
                self.btn_login_hint.setText("🔒 Fritz!OS Login in Einstellungen aktivieren für Heute / Woche / Monat")
                hdr_bg = QColor(self.config.background_color).lighter(125).name()
                alt_bg = QColor(self.config.background_color).lighter(112).name()
                self.btn_login_hint.setStyleSheet(
                    f"QPushButton {{ background-color: {hdr_bg}; color: {self.config.download_color}; "
                    f"border: 1px dashed {self.config.border_color}; border-radius: 4px; padding: 4px 8px; "
                    "font-family: 'Segoe UI'; font-size: 9.5px; font-weight: bold; }}"
                    f"QPushButton:hover {{ background-color: {alt_bg}; }}"
                )
            sess_rx = sample.session_bytes_received
            sess_tx = sample.session_bytes_sent
            sess_tot = sess_rx + sess_tx

            upnp_rx = sample.total_bytes_received
            upnp_tx = sample.total_bytes_sent
            upnp_tot = upnp_rx + upnp_tx
            uptime_label = (
                f"Seit Verbindung ({format_uptime(sample.uptime_seconds)})"
                if sample.uptime_seconds > 0
                else "Seit Router-Start"
            )
            fallback_rows = [
                (
                    "Seit Widget-Start",
                    format_bytes(sess_tot),
                    format_bytes(sess_rx),
                    format_bytes(sess_tx),
                    sess_rx,
                    sess_tx,
                ),
                (
                    uptime_label,
                    format_bytes(upnp_tot),
                    format_bytes(upnp_rx),
                    format_bytes(upnp_tx),
                    upnp_rx,
                    upnp_tx,
                ),
                ("Heute", "Login nötig", "-", "-", 0, 0),
                ("Aktuelle Woche", "Login nötig", "-", "-", 0, 0),
                ("Aktueller Monat", "Login nötig", "-", "-", 0, 0),
            ]
            for idx, (label, tot, down, up, r_rx, r_tx) in enumerate(fallback_rows):
                self.cards[idx].set_data(
                    period_name=label,
                    total_str=tot,
                    down_str=down,
                    up_str=up,
                    down_bytes=r_rx,
                    up_bytes=r_tx,
                    config=self.config,
                )
