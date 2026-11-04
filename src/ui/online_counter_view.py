"""In-widget table view with visual Download/Upload ratio bars for the Fritz!Box Online-Zähler."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.api.models import OnlineCounterStats, TrafficSample
from src.config import AppConfig
from src.ui.formatters import format_bytes, format_uptime


class RatioBarWidget(QWidget):
    """Draws a dual-color horizontal bar showing Download vs Upload share for a period."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.down_bytes: int = 0
        self.up_bytes: int = 0
        self.down_color: QColor = QColor("#FFEA00")
        self.up_color: QColor = QColor("#4A5CFF")
        self.text_color: QColor = QColor("#E0E4E8")
        self.setMinimumWidth(70)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_data(
        self,
        down_bytes: int,
        up_bytes: int,
        down_color: str,
        up_color: str,
        text_color: str,
    ) -> None:
        """Update bar values and colors without recreating the widget."""
        self.down_bytes = max(0, down_bytes)
        self.up_bytes = max(0, up_bytes)
        self.down_color = QColor(down_color)
        self.up_color = QColor(up_color)
        self.text_color = QColor(text_color)
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        total = self.down_bytes + self.up_bytes
        w = float(self.width())
        h = float(self.height())
        bar_h = min(12.0, max(8.0, h * 0.36))
        bar_y = (h - bar_h) / 2.0
        rect = QRectF(6.0, bar_y, max(10.0, w - 12.0), bar_h)

        # Track background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 22))
        painter.drawRoundedRect(rect, 4.0, 4.0)

        if total <= 0:
            return

        down_ratio = self.down_bytes / float(total)
        up_ratio = self.up_bytes / float(total)

        down_w = rect.width() * down_ratio
        up_w = rect.width() * up_ratio

        painter.save()
        painter.setClipRect(rect)
        if down_w > 0.5:
            painter.setBrush(self.down_color)
            painter.drawRoundedRect(
                QRectF(rect.left(), rect.top(), down_w, rect.height()), 3.5, 3.5
            )
        if up_w > 0.5:
            painter.setBrush(self.up_color)
            painter.drawRoundedRect(
                QRectF(rect.left() + down_w, rect.top(), up_w, rect.height()),
                3.5,
                3.5,
            )
        painter.restore()

        # If the widget is stretched wide enough, render subtle % breakdown pill in the center
        if rect.width() >= 125:
            down_pct = int(round(down_ratio * 100))
            up_pct = 100 - down_pct
            font = QFont("Segoe UI", 7, QFont.Weight.Bold)
            painter.setFont(font)
            txt = f"{down_pct}% ⬇ / {up_pct}% ⬆"
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(txt) + 10
            th = min(h - 2.0, max(bar_h + 2.0, 14.0))
            pill_rect = QRectF(
                rect.center().x() - tw / 2.0,
                (h - th) / 2.0,
                tw,
                th,
            )
            painter.setBrush(QColor(20, 26, 30, 205))
            painter.drawRoundedRect(pill_rect, 3.0, 3.0)
            painter.setPen(self.text_color)
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, txt)


class OnlineCounterView(QWidget):
    """Responsive in-widget table showing Fritz!Box Online-Zähler with visual ratio bars."""

    def __init__(
        self,
        config: AppConfig,
        on_open_settings: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.on_open_settings = on_open_settings
        self.setMinimumHeight(145)

        self._build_ui()
        self.apply_theme()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.table = QTableWidget(5, 5, self)
        self.table.setHorizontalHeaderLabels(
            ["Zeitraum", "Gesamt", "⬆ Up", "⬇ Down", "Anteil ⬇ / ⬆"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        hdr = self.table.horizontalHeader()
        hdr.setHighlightSections(False)
        for col in range(4):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        # Column 4 (Ratio bar) stretches horizontally to fill any widget width
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        # Rows stretch evenly to match whatever height the user resized the widget to
        v_hdr = self.table.verticalHeader()
        v_hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v_hdr.setMinimumSectionSize(23)

        # Pre-populate reusable items and RatioBarWidgets for all 5 rows
        for r_idx in range(5):
            for c_idx in range(4):
                item = QTableWidgetItem("")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(r_idx, c_idx, item)
            self.table.setCellWidget(r_idx, 4, RatioBarWidget())

        layout.addWidget(self.table, 1)

        # Optional hint button shown when Fritz!OS login is not yet configured
        self.btn_login_hint = QPushButton(
            "🔒 Fritz!OS Login in Einstellungen aktivieren für Heute / Woche / Monat"
        )
        self.btn_login_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_login_hint.clicked.connect(self.on_open_settings)
        self.btn_login_hint.setVisible(False)
        layout.addWidget(self.btn_login_hint)

    def apply_theme(self) -> None:
        """Apply current AppConfig colors to the table and hint button."""
        bg = QColor(self.config.background_color).darker(115).name()
        alt_bg = QColor(self.config.background_color).lighter(112).name()
        hdr_bg = QColor(self.config.background_color).lighter(125).name()
        border = self.config.border_color
        title_col = self.config.title_color

        self.table.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: {bg};
                alternate-background-color: {alt_bg};
                color: {title_col};
                border: 1px solid {border};
                border-radius: 6px;
                font-family: 'Segoe UI';
                font-size: 11px;
                outline: 0;
            }}
            QHeaderView::section {{
                background-color: {hdr_bg};
                color: {title_col};
                font-weight: bold;
                font-size: 10px;
                border: none;
                border-bottom: 1px solid {border};
                padding: 4px 7px;
            }}
            QTableWidget::item {{
                padding: 2px 7px;
                border: none;
                background: transparent;
            }}
            QTableWidget::item:hover,
            QTableWidget::item:selected,
            QTableWidget::item:focus {{
                background-color: transparent;
                border: none;
                outline: none;
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
                padding: 3px 6px;
                font-size: 10px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {alt_bg};
            }}
            """
        )

    def _set_row(
        self,
        row_idx: int,
        period_name: str,
        total_str: str,
        up_str: str,
        down_str: str,
        down_bytes: int,
        up_bytes: int,
    ) -> None:
        it_period = self.table.item(row_idx, 0)
        if it_period is not None:
            it_period.setText(f"{period_name}  ")
            it_period.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            it_period.setForeground(QColor(self.config.title_color))

        it_total = self.table.item(row_idx, 1)
        if it_total is not None:
            it_total.setText(f" {total_str} ")
            it_total.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            it_total.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            it_total.setForeground(QColor("#FFFFFF"))

        it_up = self.table.item(row_idx, 2)
        if it_up is not None:
            it_up.setText(f" {up_str} ")
            it_up.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            it_up.setFont(QFont("Segoe UI", 8))
            it_up.setForeground(QColor(self.config.upload_color))

        it_down = self.table.item(row_idx, 3)
        if it_down is not None:
            it_down.setText(f" {down_str} ")
            it_down.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            it_down.setFont(QFont("Segoe UI", 8))
            it_down.setForeground(QColor(self.config.download_color))

        bar = self.table.cellWidget(row_idx, 4)
        if isinstance(bar, RatioBarWidget):
            bar.set_data(
                down_bytes=down_bytes,
                up_bytes=up_bytes,
                down_color=self.config.download_color,
                up_color=self.config.upload_color,
                text_color=self.config.title_color,
            )

    def update_from_sample(self, sample: TrafficSample) -> None:
        """Populate the table with Online-Zähler stats or UPnP fallback counters."""
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
                self._set_row(
                    idx,
                    label,
                    format_bytes(cnt.total_bytes),
                    format_bytes(cnt.sent_bytes),
                    format_bytes(cnt.received_bytes),
                    cnt.received_bytes,
                    cnt.sent_bytes,
                )
        else:
            self.btn_login_hint.setVisible(True)
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
                    format_bytes(sess_tx),
                    format_bytes(sess_rx),
                    sess_rx,
                    sess_tx,
                ),
                (
                    uptime_label,
                    format_bytes(upnp_tot),
                    format_bytes(upnp_tx),
                    format_bytes(upnp_rx),
                    upnp_rx,
                    upnp_tx,
                ),
                ("Heute", "Login nötig", "-", "-", 0, 0),
                ("Aktuelle Woche", "Login nötig", "-", "-", 0, 0),
                ("Aktueller Monat", "Login nötig", "-", "-", 0, 0),
            ]
            for idx, (label, tot, up, down, r_rx, r_tx) in enumerate(fallback_rows):
                self._set_row(idx, label, tot, up, down, r_rx, r_tx)
