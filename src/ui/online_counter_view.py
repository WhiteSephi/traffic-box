"""In-widget table view for the Fritz!Box Online-Zähler (Variant 2)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.api.models import OnlineCounterStats, TrafficSample
from src.config import AppConfig
from src.ui.formatters import format_bytes, format_uptime


class OnlineCounterView(QWidget):
    """Compact in-widget table showing Fritz!Box Online-Zähler (Heute..Vormonat)."""

    def __init__(
        self,
        config: AppConfig,
        on_open_settings: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.on_open_settings = on_open_settings
        self.setMinimumHeight(85)

        self._build_ui()
        self.apply_theme()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self.table = QTableWidget(5, 4, self)
        self.table.setHorizontalHeaderLabels(["Zeitraum", "Gesamt", "⬆ Up", "⬇ Down"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 4):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        v_hdr = self.table.verticalHeader()
        v_hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v_hdr.setMinimumSectionSize(18)

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
                border-radius: 5px;
                font-family: 'Segoe UI';
                font-size: 11px;
            }}
            QHeaderView::section {{
                background-color: {hdr_bg};
                color: {title_col};
                font-weight: bold;
                font-size: 10px;
                border: none;
                border-bottom: 1px solid {border};
                padding: 3px 5px;
            }}
            QTableWidget::item {{
                padding: 2px 5px;
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
    ) -> None:
        it_period = QTableWidgetItem(period_name)
        it_period.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        it_period.setForeground(QColor(self.config.title_color))

        it_total = QTableWidgetItem(total_str)
        it_total.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        it_total.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        it_total.setForeground(QColor("#FFFFFF"))

        it_up = QTableWidgetItem(up_str)
        it_up.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        it_up.setForeground(QColor(self.config.upload_color))

        it_down = QTableWidgetItem(down_str)
        it_down.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        it_down.setForeground(QColor(self.config.download_color))

        self.table.setItem(row_idx, 0, it_period)
        self.table.setItem(row_idx, 1, it_total)
        self.table.setItem(row_idx, 2, it_up)
        self.table.setItem(row_idx, 3, it_down)

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
            if self.table.rowCount() != len(rows):
                self.table.setRowCount(len(rows))
            for idx, (label, cnt) in enumerate(rows):
                self._set_row(
                    idx,
                    label,
                    format_bytes(cnt.total_bytes),
                    format_bytes(cnt.sent_bytes),
                    format_bytes(cnt.received_bytes),
                )
        else:
            # Fallback view when Fritz!OS login is not yet enabled
            self.btn_login_hint.setVisible(True)
            sess_tot = sample.session_bytes_received + sample.session_bytes_sent
            upnp_tot = sample.total_bytes_received + sample.total_bytes_sent
            uptime_label = (
                f"Seit Verbindung ({format_uptime(sample.uptime_seconds)})"
                if sample.uptime_seconds > 0
                else "Seit Router-Start"
            )
            fallback_rows = [
                (
                    "Seit Widget-Start",
                    format_bytes(sess_tot),
                    format_bytes(sample.session_bytes_sent),
                    format_bytes(sample.session_bytes_received),
                ),
                (
                    uptime_label,
                    format_bytes(upnp_tot),
                    format_bytes(sample.total_bytes_sent),
                    format_bytes(sample.total_bytes_received),
                ),
                ("Heute", "Login nötig", "-", "-"),
                ("Aktuelle Woche", "Login nötig", "-", "-"),
                ("Aktueller Monat", "Login nötig", "-", "-"),
            ]
            if self.table.rowCount() != len(fallback_rows):
                self.table.setRowCount(len(fallback_rows))
            for idx, (label, tot, up, down) in enumerate(fallback_rows):
                self._set_row(idx, label, tot, up, down)
