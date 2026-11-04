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
        self._ping_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)
        self._jitter_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)

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
        ping_ms: float | None = None,
        jitter_ms: float = 0.0,
    ) -> None:
        """Append a new sample to the time series and trigger a repaint."""
        target_len = max(15, self.config.history_seconds)
        if self._down_history.maxlen != target_len:
            self._down_history = deque(self._down_history, maxlen=target_len)
            self._up_history = deque(self._up_history, maxlen=target_len)
            self._guest_down_history = deque(self._guest_down_history, maxlen=target_len)
            self._guest_up_history = deque(self._guest_up_history, maxlen=target_len)
            self._ping_history = deque(self._ping_history, maxlen=target_len)
            self._jitter_history = deque(self._jitter_history, maxlen=target_len)

        self._down_history.append(max(0.0, down_bps))
        self._up_history.append(max(0.0, up_bps))
        self._guest_down_history.append(max(0.0, min(down_bps, guest_down_bps)))
        self._guest_up_history.append(max(0.0, min(up_bps, guest_up_bps)))
        self._ping_history.append(max(0.0, ping_ms) if ping_ms is not None else 0.0)
        self._jitter_history.append(max(0.0, jitter_ms))

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

    def _draw_ping_jitter_graph(
        self,
        painter: QPainter,
        rect: QRectF,
        ping_series: deque[float],
        jitter_series: deque[float],
        grid_color: QColor,
    ) -> None:
        """Draw Ping & Jitter sub-graph with dual curves, Min/Max stats, and live value badges."""
        painter.save()
        painter.setClipRect(rect)

        # 1. Background Grid (2 horizontal subdivisions, 10 vertical subdivisions)
        grid_pen = QPen(grid_color, 1.0, Qt.PenStyle.SolidLine)
        painter.setPen(grid_pen)

        rows = 2
        cols = 10
        for r in range(1, rows):
            y = rect.top() + (rect.height() * r / rows)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        for c in range(1, cols):
            x = rect.left() + (rect.width() * c / cols)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

        # Outer border
        border_pen = QPen(QColor(self.config.border_color), 1.0)
        painter.setPen(border_pen)
        painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

        # Dynamic scale for ping/jitter (min ceiling 20ms or max ping * 1.25)
        active_pings = [v for v in ping_series if v > 0]
        max_ping = max(active_pings) if active_pings else 20.0
        min_ping = min(active_pings) if active_pings else 0.0
        ceiling = max(20.0, max_ping * 1.25)

        count = len(ping_series)
        last_ping_y: float | None = None
        last_jitter_y: float | None = None
        last_ping_val: float = ping_series[-1] if count > 0 else 0.0
        last_jitter_val: float = jitter_series[-1] if len(jitter_series) > 0 else 0.0

        if count >= 2:
            step_x = rect.width() / float(count - 1)

            # --- Ping Curve & Area ---
            ping_line = QPainterPath()
            ping_area = QPainterPath()
            ping_area.moveTo(rect.left(), rect.bottom())

            for idx, val in enumerate(ping_series):
                x = rect.left() + idx * step_x
                norm_h = min(1.0, max(0.0, val / ceiling))
                y = rect.bottom() - (norm_h * (rect.height() - 14.0)) - 1.0
                if idx == 0:
                    ping_line.moveTo(x, y)
                else:
                    ping_line.lineTo(x, y)
                ping_area.lineTo(x, y)
                if idx == count - 1:
                    last_ping_y = y

            ping_area.lineTo(rect.right(), rect.bottom())
            ping_area.closeSubpath()

            ping_col = QColor(self.config.ping_color)
            grad = QLinearGradient(0.0, rect.top(), 0.0, rect.bottom())
            top_fill = QColor(ping_col)
            top_fill.setAlpha(90)
            bot_fill = QColor(ping_col)
            bot_fill.setAlpha(15)
            grad.setColorAt(0.0, top_fill)
            grad.setColorAt(1.0, bot_fill)
            painter.fillPath(ping_area, grad)

            ping_pen = QPen(ping_col, 1.5)
            ping_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(ping_pen)
            painter.drawPath(ping_line)

            # --- Jitter Curve ---
            jitter_col = QColor(self.config.jitter_color)
            jitter_line = QPainterPath()
            jitter_pts = []
            for idx, j_val in enumerate(jitter_series):
                x = rect.left() + idx * step_x
                norm_h = min(1.0, max(0.0, j_val / ceiling))
                y = rect.bottom() - (norm_h * (rect.height() - 14.0)) - 1.0
                if idx == 0:
                    jitter_line.moveTo(x, y)
                else:
                    jitter_line.lineTo(x, y)
                jitter_pts.append(QPointF(x, y))
                if idx == count - 1:
                    last_jitter_y = y

            jitter_pen = QPen(jitter_col, 1.2, Qt.PenStyle.SolidLine)
            painter.setPen(jitter_pen)
            painter.drawPath(jitter_line)

            # Draw small marker dots for jitter peaks
            painter.setBrush(jitter_col)
            painter.setPen(Qt.PenStyle.NoPen)
            for idx, pt in enumerate(jitter_pts):
                if jitter_series[idx] > 1.5:
                    painter.drawEllipse(pt, 1.5, 1.5)

        # Header Legend & Stats
        font_pt = max(7, min(9, int(round(7.0 * max(1.0, self.height() / 150.0)))))
        font = QFont("Segoe UI", font_pt)
        painter.setFont(font)

        # Left legend: ◆ Ping (Cyan)   ▲ Jitter (Amber)
        legend_left = rect.left() + 5.0
        legend_top = rect.top() + 2.0

        painter.setPen(QColor(self.config.ping_color))
        painter.drawText(QPointF(legend_left, legend_top + font_pt + 1), "◆ Ping")

        painter.setPen(QColor(self.config.jitter_color))
        painter.drawText(QPointF(legend_left + 48.0, legend_top + font_pt + 1), "▲ Jitter")

        # Right stats: Min / Max
        if active_pings:
            stats_text = f"Min: {min_ping:.1f} ms  Max: {max_ping:.1f} ms"
            label_col = QColor(self.config.title_color)
            label_col.setAlpha(135)
            painter.setPen(label_col)
            painter.drawText(
                rect.adjusted(4, 2, -5, -2),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                stats_text,
            )

        # Right-edge live pill badges for Ping & Jitter
        if last_ping_y is not None and last_ping_val > 0:
            badge_font = QFont("Segoe UI", 7, QFont.Weight.Bold)
            painter.setFont(badge_font)

            ping_txt = f"{last_ping_val:.1f} ms"
            p_rect = QRectF(rect.right() - 44.0, max(rect.top() + 2.0, min(rect.bottom() - 14.0, last_ping_y - 6.0)), 42.0, 12.0)
            painter.setBrush(QColor(self.config.ping_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(p_rect, 3.0, 3.0)
            painter.setPen(QColor("#000000"))
            painter.drawText(p_rect, Qt.AlignmentFlag.AlignCenter, ping_txt)

        if last_jitter_y is not None and last_jitter_val >= 0:
            badge_font = QFont("Segoe UI", 7, QFont.Weight.Bold)
            painter.setFont(badge_font)

            jit_txt = f"{last_jitter_val:.1f} ms"
            # Offset slightly if close to ping badge
            jit_y = last_jitter_y - 6.0
            if last_ping_y is not None and abs(last_ping_y - last_jitter_y) < 14.0:
                jit_y = last_jitter_y + 7.0
            j_rect = QRectF(rect.right() - 44.0, max(rect.top() + 2.0, min(rect.bottom() - 14.0, jit_y)), 42.0, 12.0)
            painter.setBrush(QColor(self.config.jitter_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(j_rect, 3.0, 3.0)
            painter.setPen(QColor("#000000"))
            painter.drawText(j_rect, Qt.AlignmentFlag.AlignCenter, jit_txt)

        painter.restore()

    def paintEvent(self, _event: object) -> None:
        """Render the split graphs (2-way traffic only or 3-way with Ping & Jitter)."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        gap = 3.0

        down_color = QColor(self.config.download_color)
        up_color = QColor(self.config.upload_color)
        guest_down_color = QColor(self.config.guest_download_color)
        guest_up_color = QColor(self.config.guest_upload_color)
        grid_color = QColor(self.config.grid_color)

        if not self.config.enable_ping_graph:
            # Standard 2-graph layout
            half_h = (h - gap) / 2.0
            top_rect = QRectF(0.0, 0.0, w, half_h)
            bottom_rect = QRectF(0.0, half_h + gap, w, half_h)

            if self.config.switch_up_down:
                self._draw_single_graph(
                    painter, top_rect, self._down_history, self._guest_down_history,
                    self._max_down_bps, down_color, guest_down_color, grid_color,
                )
                self._draw_single_graph(
                    painter, bottom_rect, self._up_history, self._guest_up_history,
                    self._max_up_bps, up_color, guest_up_color, grid_color,
                )
            else:
                self._draw_single_graph(
                    painter, top_rect, self._up_history, self._guest_up_history,
                    self._max_up_bps, up_color, guest_up_color, grid_color,
                )
                self._draw_single_graph(
                    painter, bottom_rect, self._down_history, self._guest_down_history,
                    self._max_down_bps, down_color, guest_down_color, grid_color,
                )
        else:
            # 3-graph layout: Traffic (Down/Up) + Ping/Jitter
            net_h = h - 2.0 * gap
            # Allocate ~38% to Down, ~38% to Up, ~24% to Ping/Jitter
            traffic_h = max(26.0, math.floor(net_h * 0.38))
            ping_h = max(24.0, net_h - 2.0 * traffic_h)

            top_rect = QRectF(0.0, 0.0, w, traffic_h)
            mid_rect = QRectF(0.0, traffic_h + gap, w, traffic_h)
            ping_rect = QRectF(0.0, 2.0 * traffic_h + 2.0 * gap, w, ping_h)

            if self.config.switch_up_down:
                self._draw_single_graph(
                    painter, top_rect, self._down_history, self._guest_down_history,
                    self._max_down_bps, down_color, guest_down_color, grid_color,
                )
                self._draw_single_graph(
                    painter, mid_rect, self._up_history, self._guest_up_history,
                    self._max_up_bps, up_color, guest_up_color, grid_color,
                )
            else:
                self._draw_single_graph(
                    painter, top_rect, self._up_history, self._guest_up_history,
                    self._max_up_bps, up_color, guest_up_color, grid_color,
                )
                self._draw_single_graph(
                    painter, mid_rect, self._down_history, self._guest_down_history,
                    self._max_down_bps, down_color, guest_down_color, grid_color,
                )

            self._draw_ping_jitter_graph(
                painter, ping_rect, self._ping_history, self._jitter_history, grid_color,
            )
