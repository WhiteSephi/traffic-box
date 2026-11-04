"""Custom split-area live traffic graph widget using Qt6 QPainter."""

from __future__ import annotations

from collections import deque
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

from src.config import AppConfig
from src.ui.formatters import format_rate


class SplitTrafficGraphWidget(QWidget):
    """Renders top and bottom real-time oscilloscope area graphs for Down/Up + Guest share."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setMinimumHeight(85)

        max_len = max(15, self.config.history_seconds)
        self._down_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)
        self._up_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)
        self._guest_down_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)
        self._guest_up_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)

        self._max_down_bps: float = (self.config.manual_download_mbps * 1_000_000.0) / 8.0
        self._max_up_bps: float = (self.config.manual_upload_mbps * 1_000_000.0) / 8.0

    @property
    def current_peak_down_bps(self) -> float:
        """Return the highest download rate within the visible graph time window."""
        return max(self._down_history) if self._down_history else 0.0

    @property
    def current_peak_up_bps(self) -> float:
        """Return the highest upload rate within the visible graph time window."""
        return max(self._up_history) if self._up_history else 0.0

    def push_sample(
        self,
        down_bps: float,
        up_bps: float,
        guest_down_bps: float,
        guest_up_bps: float,
        link_max_down_bps: float,
        link_max_up_bps: float,
    ) -> None:
        """Append a new sample to the time series and trigger a repaint."""
        target_len = max(15, self.config.history_seconds)
        if self._down_history.maxlen != target_len:
            self._down_history = deque(self._down_history, maxlen=target_len)
            self._up_history = deque(self._up_history, maxlen=target_len)
            self._guest_down_history = deque(self._guest_down_history, maxlen=target_len)
            self._guest_up_history = deque(self._guest_up_history, maxlen=target_len)

        self._down_history.append(max(0.0, down_bps))
        self._up_history.append(max(0.0, up_bps))
        self._guest_down_history.append(max(0.0, min(down_bps, guest_down_bps)))
        self._guest_up_history.append(max(0.0, min(up_bps, guest_up_bps)))

        if self.config.auto_link_scale and link_max_down_bps > 0:
            self._max_down_bps = link_max_down_bps
        else:
            self._max_down_bps = max(1024.0, (self.config.manual_download_mbps * 1_000_000.0) / 8.0)

        if self.config.auto_link_scale and link_max_up_bps > 0:
            self._max_up_bps = link_max_up_bps
        else:
            self._max_up_bps = max(1024.0, (self.config.manual_upload_mbps * 1_000_000.0) / 8.0)

        self.update()

    def _compute_normalized_y(self, value: float, ceiling: float) -> float:
        """Map a throughput value in [0, ceiling] to a normalized height in [0.0, 1.0]."""
        if ceiling <= 0.0 or value <= 0.0:
            return 0.0
        ratio = min(1.0, max(0.0, value / ceiling))
        if self.config.scale_mode == "sqrt":
            return math.sqrt(ratio)
        return ratio

    def _effective_ceiling(self, series: deque[float], max_line_bps: float) -> float:
        """Determine the graph ceiling based on the configured scale_mode."""
        if self.config.scale_mode == "dynamic":
            peak = max(series) if series else 0.0
            # Keep at least 32 kB/s minimum ceiling so idle noise stays flat
            return max(32 * 1024.0, peak * 1.15)
        return max(1024.0, max_line_bps)

    def _draw_single_graph(
        self,
        painter: QPainter,
        rect: QRectF,
        main_series: deque[float],
        guest_series: deque[float],
        max_line_bps: float,
        main_color: QColor,
        guest_color: QColor,
        grid_color: QColor,
    ) -> None:
        """Draw grid, main area curve, optional guest overlay, and scale badge."""
        painter.save()
        painter.setClipRect(rect)

        # 1. Background Grid (4 horizontal subdivisions, 10 vertical subdivisions)
        grid_pen = QPen(grid_color, 1.0, Qt.PenStyle.SolidLine)
        painter.setPen(grid_pen)

        rows = 4
        cols = 10
        for r in range(1, rows):
            y = rect.top() + (rect.height() * r / rows)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        for c in range(1, cols):
            x = rect.left() + (rect.width() * c / cols)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

        # Outer frame of sub-graph
        border_pen = QPen(QColor(self.config.border_color), 1.0)
        painter.setPen(border_pen)
        painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

        ceiling = self._effective_ceiling(main_series, max_line_bps)
        count = len(main_series)
        if count >= 2:
            step_x = rect.width() / float(count - 1)

            # Build main curve path
            line_path = QPainterPath()
            area_path = QPainterPath()
            area_path.moveTo(rect.left(), rect.bottom())

            for idx, val in enumerate(main_series):
                x = rect.left() + idx * step_x
                norm_h = self._compute_normalized_y(val, ceiling)
                # Leave 2px breathing room at the very top
                y = rect.bottom() - (norm_h * (rect.height() - 3.0)) - 1.0
                if idx == 0:
                    line_path.moveTo(x, y)
                else:
                    line_path.lineTo(x, y)
                area_path.lineTo(x, y)

            area_path.lineTo(rect.right(), rect.bottom())
            area_path.closeSubpath()

            # Fill with smooth vertical gradient
            grad = QLinearGradient(0.0, rect.top(), 0.0, rect.bottom())
            top_fill = QColor(main_color)
            top_fill.setAlpha(155)
            bottom_fill = QColor(main_color)
            bottom_fill.setAlpha(35)
            grad.setColorAt(0.0, top_fill)
            grad.setColorAt(1.0, bottom_fill)
            painter.fillPath(area_path, grad)

            # Stroke main curve
            curve_pen = QPen(main_color, 1.8)
            curve_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(curve_pen)
            painter.drawPath(line_path)

            # Optional Guest Wi-Fi overlay at the bottom of the graph
            if self.config.enable_guest_monitor and any(v > 0 for v in guest_series):
                guest_line = QPainterPath()
                guest_area = QPainterPath()
                guest_area.moveTo(rect.left(), rect.bottom())
                for idx, g_val in enumerate(guest_series):
                    x = rect.left() + idx * step_x
                    norm_h = self._compute_normalized_y(g_val, ceiling)
                    y = rect.bottom() - (norm_h * (rect.height() - 3.0)) - 1.0
                    if idx == 0:
                        guest_line.moveTo(x, y)
                    else:
                        guest_line.lineTo(x, y)
                    guest_area.lineTo(x, y)
                guest_area.lineTo(rect.right(), rect.bottom())
                guest_area.closeSubpath()

                g_fill = QColor(guest_color)
                g_fill.setAlpha(140)
                painter.fillPath(guest_area, g_fill)
                painter.setPen(QPen(guest_color, 1.4, Qt.PenStyle.DashLine))
                painter.drawPath(guest_line)

        # Subtle scale label in top-right corner of the sub-graph
        scale_tag = {
            "sqrt": "√-Skala",
            "dynamic": "Dyn",
            "fixed": "Max",
        }.get(self.config.scale_mode, "Max")
        ceil_text = f"{scale_tag}: {format_rate(ceiling, self.config.show_as_bits)}"
        font_pt = max(7, min(10, int(round(7.0 * max(1.0, self.height() / 150.0)))))
        font = QFont("Segoe UI", font_pt)
        painter.setFont(font)
        label_color = QColor(self.config.title_color)
        label_color.setAlpha(135)
        painter.setPen(label_color)
        painter.drawText(
            rect.adjusted(4, 2, -5, -2),
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
            ceil_text,
        )

        painter.restore()

    def paintEvent(self, _event: object) -> None:
        """Render the split top and bottom graphs."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        gap = 3.0
        half_h = (h - gap) / 2.0

        top_rect = QRectF(0.0, 0.0, w, half_h)
        bottom_rect = QRectF(0.0, half_h + gap, w, half_h)

        down_color = QColor(self.config.download_color)
        up_color = QColor(self.config.upload_color)
        guest_down_color = QColor(self.config.guest_download_color)
        guest_up_color = QColor(self.config.guest_upload_color)
        grid_color = QColor(self.config.grid_color)

        if self.config.switch_up_down:
            # Download on top, Upload on bottom (like user's screenshot)
            self._draw_single_graph(
                painter,
                top_rect,
                self._down_history,
                self._guest_down_history,
                self._max_down_bps,
                down_color,
                guest_down_color,
                grid_color,
            )
            self._draw_single_graph(
                painter,
                bottom_rect,
                self._up_history,
                self._guest_up_history,
                self._max_up_bps,
                up_color,
                guest_up_color,
                grid_color,
            )
        else:
            # Upload on top, Download on bottom
            self._draw_single_graph(
                painter,
                top_rect,
                self._up_history,
                self._guest_up_history,
                self._max_up_bps,
                up_color,
                guest_up_color,
                grid_color,
            )
            self._draw_single_graph(
                painter,
                bottom_rect,
                self._down_history,
                self._guest_down_history,
                self._max_down_bps,
                down_color,
                guest_down_color,
                grid_color,
            )
