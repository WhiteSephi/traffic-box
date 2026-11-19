"""Custom split-area live traffic graph widget using Qt6 QPainter."""

from __future__ import annotations

from collections import deque
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

from src.config import AppConfig
from src.ui.formatters import format_rate


class SplitTrafficGraphWidget(QWidget):
    """Renders top and bottom real-time oscilloscope area graphs for Down/Up + Guest share."""

    point_hovered = Signal(int, int, float, float, float, float)
    point_unhovered = Signal()

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setMinimumHeight(max(60, int(round(85.0 * self.config.ui_scale))))
        self.setMouseTracking(True)

        self._hover_idx: int | None = None
        self._hover_x: float | None = None
        self._hover_mouse_y: float | None = None

        max_len = max(15, self.config.history_seconds)
        self._down_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)
        self._up_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)
        self._guest_down_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)
        self._guest_up_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)
        self._pc_down_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)
        self._pc_up_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)
        self._ping_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)
        self._ping_loss_history: deque[bool] = deque([False] * max_len, maxlen=max_len)
        self._jitter_history: deque[float] = deque([0.0] * max_len, maxlen=max_len)

        self._max_down_bps: float = (self.config.manual_download_mbps * 1_000_000.0) / 8.0
        self._max_up_bps: float = (self.config.manual_upload_mbps * 1_000_000.0) / 8.0
        self._is_local_fallback: bool = False

    @property
    def current_ceiling_down_bps(self) -> float:
        """Return the effective download graph ceiling in bytes/sec."""
        return self._effective_ceiling(self._down_history, self._max_down_bps)

    @property
    def current_ceiling_up_bps(self) -> float:
        """Return the effective upload graph ceiling in bytes/sec."""
        return self._effective_ceiling(self._up_history, self._max_up_bps)

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
        pc_down_bps: float = 0.0,
        pc_up_bps: float = 0.0,
        is_local_fallback: bool = False,
        ping_lost: bool = False,
    ) -> None:
        """Append a new sample to the time series and trigger a repaint."""
        self._is_local_fallback = is_local_fallback
        target_len = max(15, self.config.history_seconds)
        if self._down_history.maxlen != target_len:
            self._down_history = deque(self._down_history, maxlen=target_len)
            self._up_history = deque(self._up_history, maxlen=target_len)
            self._guest_down_history = deque(self._guest_down_history, maxlen=target_len)
            self._guest_up_history = deque(self._guest_up_history, maxlen=target_len)
            self._pc_down_history = deque(self._pc_down_history, maxlen=target_len)
            self._pc_up_history = deque(self._pc_up_history, maxlen=target_len)
            self._ping_history = deque(self._ping_history, maxlen=target_len)
            self._ping_loss_history = deque(self._ping_loss_history, maxlen=target_len)
            self._jitter_history = deque(self._jitter_history, maxlen=target_len)

        self._down_history.append(max(0.0, down_bps))
        self._up_history.append(max(0.0, up_bps))
        self._guest_down_history.append(max(0.0, min(down_bps, guest_down_bps)))
        self._guest_up_history.append(max(0.0, min(up_bps, guest_up_bps)))
        self._pc_down_history.append(max(0.0, min(down_bps, pc_down_bps)))
        self._pc_up_history.append(max(0.0, min(up_bps, pc_up_bps)))
        self._ping_history.append(max(0.0, ping_ms) if (ping_ms is not None and not ping_lost) else 0.0)
        self._ping_loss_history.append(bool(ping_lost))
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
        if self.config.scale_mode == "dynamic" or (
            self._is_local_fallback and self.config.auto_link_scale
        ):
            peak = max(series) if series else 0.0
            # Keep at least 1 Mbit/s (125 kB/s) in fallback or 32 kB/s in dynamic mode
            min_floor = 125_000.0 if self._is_local_fallback else 32 * 1024.0
            return max(min_floor, peak * 1.15)
        return max(1024.0, max_line_bps)

    def _draw_single_graph(
        self,
        painter: QPainter,
        rect: QRectF,
        main_series: deque[float],
        guest_series: deque[float],
        pc_series: deque[float],
        max_line_bps: float,
        main_color: QColor,
        guest_color: QColor,
        grid_color: QColor,
        legend_text: str = "",
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

            # Optional Local PC share overlay (derived darker shade of main curve)
            if (
                self.config.enable_local_traffic_monitor
                and self.config.show_local_traffic_in_graph
                and any(v > 0 for v in pc_series)
            ):
                pc_line = QPainterPath()
                pc_area = QPainterPath()
                pc_area.moveTo(rect.left(), rect.bottom())
                for idx, p_val in enumerate(pc_series):
                    x = rect.left() + idx * step_x
                    norm_h = self._compute_normalized_y(p_val, ceiling)
                    y = rect.bottom() - (norm_h * (rect.height() - 3.0)) - 1.0
                    if idx == 0:
                        pc_line.moveTo(x, y)
                    else:
                        pc_line.lineTo(x, y)
                    pc_area.lineTo(x, y)
                pc_area.lineTo(rect.right(), rect.bottom())
                pc_area.closeSubpath()

                # Derive darker tone from main color
                pc_color = QColor(main_color).darker(150)
                pc_fill = QColor(pc_color)
                pc_fill.setAlpha(175)
                painter.fillPath(pc_area, pc_fill)

                pc_pen = QPen(pc_color, 1.4, Qt.PenStyle.SolidLine)
                pc_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pc_pen)
                painter.drawPath(pc_line)

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
        if self._is_local_fallback and self.config.auto_link_scale and self.config.scale_mode != "dynamic":
            scale_tag = "Dyn (√)" if self.config.scale_mode == "sqrt" else "Dyn"
        else:
            scale_tag = {
                "sqrt": "√-Skala",
                "dynamic": "Dyn",
                "fixed": "Max",
            }.get(self.config.scale_mode, "Max")
        ceil_text = f"{scale_tag}: {format_rate(ceiling, self.config.show_as_bits)}"
        base_s = self.config.ui_scale
        font_pt = max(7, min(14, int(round(7.0 * base_s * max(1.0, self.height() / (150.0 * base_s))))))
        font = QFont("Segoe UI", font_pt)
        painter.setFont(font)

        # Left legend (e.g. "↓ Down" / "↑ Up") analogous to Ping/Jitter
        if legend_text:
            fm = QFontMetrics(font)
            legend_left = rect.left() + 5.0 * base_s
            legend_top = rect.top() + 2.0 * base_s
            painter.setPen(main_color)
            painter.drawText(QPointF(legend_left, legend_top + fm.ascent()), legend_text)

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
        active_pings = [
            v for idx, v in enumerate(ping_series)
            if v > 0 and not (idx < len(self._ping_loss_history) and self._ping_loss_history[idx])
        ]
        max_ping = max(active_pings) if active_pings else 20.0
        min_ping = min(active_pings) if active_pings else 0.0
        ceiling = max(20.0, max_ping * 1.25)

        count = len(ping_series)
        last_ping_y: float | None = None
        last_jitter_y: float | None = None
        last_is_lost: bool = self._ping_loss_history[-1] if self._ping_loss_history else False
        last_ping_val: float = ping_series[-1] if (count > 0 and not last_is_lost) else 0.0
        last_jitter_val: float = jitter_series[-1] if len(jitter_series) > 0 else 0.0

        loss_indices: list[int] = []
        measured_count = 0

        if count >= 2:
            step_x = rect.width() / float(count - 1)
            ping_col = QColor(self.config.ping_color)
            grad = QLinearGradient(0.0, rect.top(), 0.0, rect.bottom())
            top_fill = QColor(ping_col)
            top_fill.setAlpha(90)
            bot_fill = QColor(ping_col)
            bot_fill.setAlpha(15)
            grad.setColorAt(0.0, top_fill)
            grad.setColorAt(1.0, bot_fill)

            ping_pen = QPen(ping_col, 1.5)
            ping_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

            # --- Ping Curve & Area (broken into segments on packet loss) ---
            seg_points: list[QPointF] = []

            def _flush_segment(pts: list[QPointF]) -> None:
                if not pts:
                    return
                if len(pts) >= 2:
                    seg_line = QPainterPath()
                    seg_area = QPainterPath()
                    seg_area.moveTo(pts[0].x(), rect.bottom())
                    for s_i, pt in enumerate(pts):
                        if s_i == 0:
                            seg_line.moveTo(pt)
                        else:
                            seg_line.lineTo(pt)
                        seg_area.lineTo(pt)
                    seg_area.lineTo(pts[-1].x(), rect.bottom())
                    seg_area.closeSubpath()
                    painter.fillPath(seg_area, grad)
                    painter.setPen(ping_pen)
                    painter.drawPath(seg_line)
                else:
                    painter.setBrush(ping_col)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(pts[0], 1.6, 1.6)

            for idx, val in enumerate(ping_series):
                is_lost = idx < len(self._ping_loss_history) and self._ping_loss_history[idx]
                if is_lost:
                    loss_indices.append(idx)
                    measured_count += 1
                    _flush_segment(seg_points)
                    seg_points = []
                    continue

                if val > 0:
                    measured_count += 1
                x = rect.left() + idx * step_x
                norm_h = min(1.0, max(0.0, val / ceiling))
                y = rect.bottom() - (norm_h * (rect.height() - 14.0)) - 1.0
                seg_points.append(QPointF(x, y))
                if idx == count - 1:
                    last_ping_y = y

            _flush_segment(seg_points)

            # Draw subtle red loss markers at lost ping slots
            if loss_indices:
                loss_pen = QPen(QColor(255, 82, 82, 185), 1.6)
                painter.setPen(loss_pen)
                for l_idx in loss_indices:
                    lx = rect.left() + l_idx * step_x
                    painter.drawLine(QPointF(lx, rect.bottom() - 8.0), QPointF(lx, rect.bottom() - 1.0))

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
        base_s = self.config.ui_scale
        font_pt = max(7, min(14, int(round(7.0 * base_s * max(1.0, self.height() / (150.0 * base_s))))))
        font = QFont("Segoe UI", font_pt)
        painter.setFont(font)

        # Left legend: ◆ Ping (Cyan)   ▲ Jitter (Amber)
        fm = QFontMetrics(font)
        legend_left = rect.left() + 5.0 * base_s
        legend_top = rect.top() + 2.0 * base_s
        legend_y = legend_top + fm.ascent()
        ping_label = "◆ Ping"

        painter.setPen(QColor(self.config.ping_color))
        painter.drawText(QPointF(legend_left, legend_y), ping_label)

        jitter_left = legend_left + fm.horizontalAdvance(ping_label) + 10.0 * base_s
        painter.setPen(QColor(self.config.jitter_color))
        painter.drawText(QPointF(jitter_left, legend_y), "▲ Jitter")

        # Right stats: Min / Max (+ Loss %)
        loss_pct = (len(loss_indices) / measured_count * 100.0) if (loss_indices and measured_count > 0) else 0.0
        stats_rect = rect.adjusted(4, 2, -5, -2)
        if active_pings:
            stats_text = f"Min: {min_ping:.1f} ms  Max: {max_ping:.1f} ms"
            label_col = QColor(self.config.title_color)
            label_col.setAlpha(135)
            painter.setPen(label_col)
            painter.drawText(
                stats_rect,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                stats_text,
            )
            if loss_pct > 0.0:
                loss_text = f"Loss: {loss_pct:.0f}%  "
                stats_w = fm.horizontalAdvance(stats_text)
                loss_w = fm.horizontalAdvance(loss_text)
                painter.setPen(QColor("#FF5252"))
                painter.drawText(
                    QPointF(stats_rect.right() - stats_w - loss_w, legend_y),
                    loss_text,
                )
        elif loss_pct > 0.0:
            painter.setPen(QColor("#FF5252"))
            painter.drawText(
                stats_rect,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                f"Loss: {loss_pct:.0f}%",
            )

        # Right-edge live pill badges for Ping & Jitter
        badge_pt = max(6, int(round(7.0 * base_s)))
        badge_w = max(42.0, 44.0 * base_s)
        badge_h = max(12.0, 12.0 * base_s)
        if last_ping_y is not None and last_ping_val > 0:
            badge_font = QFont("Segoe UI", badge_pt, QFont.Weight.Bold)
            painter.setFont(badge_font)

            ping_txt = f"{last_ping_val:.1f} ms"
            p_rect = QRectF(rect.right() - badge_w - 2.0, max(rect.top() + 2.0, min(rect.bottom() - (badge_h + 2.0), last_ping_y - (badge_h / 2.0))), badge_w, badge_h)
            painter.setBrush(QColor(self.config.ping_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(p_rect, 3.0 * base_s, 3.0 * base_s)
            painter.setPen(QColor("#000000"))
            painter.drawText(p_rect, Qt.AlignmentFlag.AlignCenter, ping_txt)

        if last_jitter_y is not None and last_jitter_val >= 0:
            badge_font = QFont("Segoe UI", badge_pt, QFont.Weight.Bold)
            painter.setFont(badge_font)

            jit_txt = f"{last_jitter_val:.1f} ms"
            # Offset slightly if close to ping badge
            jit_y = last_jitter_y - (badge_h / 2.0)
            if last_ping_y is not None and abs(last_ping_y - last_jitter_y) < (badge_h + 2.0):
                jit_y = last_jitter_y + (badge_h / 2.0) + 1.0
            j_rect = QRectF(rect.right() - badge_w - 2.0, max(rect.top() + 2.0, min(rect.bottom() - (badge_h + 2.0), jit_y)), badge_w, badge_h)
            painter.setBrush(QColor(self.config.jitter_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(j_rect, 3.0 * base_s, 3.0 * base_s)
            painter.setPen(QColor("#000000"))
            painter.drawText(j_rect, Qt.AlignmentFlag.AlignCenter, jit_txt)

        painter.restore()

    def event(self, event: QEvent) -> bool:
        """Suppress parent window tooltip popups over the interactive graph canvas."""
        if event.type() == QEvent.Type.ToolTip:
            return True
        return super().event(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Ignore left clicks so parent window can be moved by dragging."""
        if event.button() == Qt.MouseButton.LeftButton:
            event.ignore()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handle mouse hover to track and inspect measurement points."""
        if event.buttons() & Qt.MouseButton.LeftButton:
            event.ignore()
            return

        count = len(self._down_history)
        w = float(self.width())
        if count < 2 or w <= 0:
            return

        mx = max(0.0, min(w, event.position().x()))
        step_x = w / float(count - 1)
        idx = max(0, min(count - 1, int(round(mx / step_x))))

        self._hover_idx = idx
        self._hover_x = idx * step_x
        self._hover_mouse_y = event.position().y()

        age_sec = int(round((count - 1 - idx) * self.config.refresh_interval_sec))
        val_down = self._down_history[idx] if idx < len(self._down_history) else 0.0
        val_up = self._up_history[idx] if idx < len(self._up_history) else 0.0
        val_ping = self._ping_history[idx] if idx < len(self._ping_history) else 0.0
        val_jitter = self._jitter_history[idx] if idx < len(self._jitter_history) else 0.0

        self.point_hovered.emit(idx, age_sec, val_down, val_up, val_ping, val_jitter)
        self.update()

    def leaveEvent(self, _event: object) -> None:
        """Reset hover crosshair and notify parent when mouse leaves canvas."""
        if self._hover_idx is not None:
            self._hover_idx = None
            self._hover_x = None
            self._hover_mouse_y = None
            self.point_unhovered.emit()
            self.update()

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
            ping_rect = None

            if self.config.switch_up_down:
                down_rect = top_rect
                up_rect = bottom_rect
                self._draw_single_graph(
                    painter, top_rect, self._down_history, self._guest_down_history,
                    self._pc_down_history, self._max_down_bps, down_color, guest_down_color, grid_color, "↓ Down",
                )
                self._draw_single_graph(
                    painter, bottom_rect, self._up_history, self._guest_up_history,
                    self._pc_up_history, self._max_up_bps, up_color, guest_up_color, grid_color, "↑ Up",
                )
            else:
                up_rect = top_rect
                down_rect = bottom_rect
                self._draw_single_graph(
                    painter, top_rect, self._up_history, self._guest_up_history,
                    self._pc_up_history, self._max_up_bps, up_color, guest_up_color, grid_color, "↑ Up",
                )
                self._draw_single_graph(
                    painter, bottom_rect, self._down_history, self._guest_down_history,
                    self._pc_down_history, self._max_down_bps, down_color, guest_down_color, grid_color, "↓ Down",
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
                down_rect = top_rect
                up_rect = mid_rect
                self._draw_single_graph(
                    painter, top_rect, self._down_history, self._guest_down_history,
                    self._pc_down_history, self._max_down_bps, down_color, guest_down_color, grid_color, "↓ Down",
                )
                self._draw_single_graph(
                    painter, mid_rect, self._up_history, self._guest_up_history,
                    self._pc_up_history, self._max_up_bps, up_color, guest_up_color, grid_color, "↑ Up",
                )
            else:
                up_rect = top_rect
                down_rect = mid_rect
                self._draw_single_graph(
                    painter, top_rect, self._up_history, self._guest_up_history,
                    self._pc_up_history, self._max_up_bps, up_color, guest_up_color, grid_color, "↑ Up",
                )
                self._draw_single_graph(
                    painter, mid_rect, self._down_history, self._guest_down_history,
                    self._pc_down_history, self._max_down_bps, down_color, guest_down_color, grid_color, "↓ Down",
                )

            self._draw_ping_jitter_graph(
                painter, ping_rect, self._ping_history, self._jitter_history, grid_color,
            )

        if self._hover_idx is not None and self._hover_x is not None:
            self._draw_hover_overlay(
                painter,
                w,
                h,
                down_rect,
                up_rect,
                ping_rect,
                down_color,
                up_color,
            )

    def _draw_hover_overlay(
        self,
        painter: QPainter,
        w: float,
        h: float,
        down_rect: QRectF,
        up_rect: QRectF,
        ping_rect: QRectF | None,
        down_color: QColor,
        up_color: QColor,
    ) -> None:
        """Render crosshair, curve dots, and floating HUD badge at hovered position."""
        idx = self._hover_idx
        if idx is None or idx < 0 or idx >= len(self._down_history):
            return

        painter.save()
        x = self._hover_x if self._hover_x is not None else 0.0

        # 1. Vertical Dash Line across full height
        dash_pen = QPen(QColor(230, 235, 245, 140), 1.0, Qt.PenStyle.DashLine)
        dash_pen.setDashPattern([3, 3])
        painter.setPen(dash_pen)
        painter.drawLine(QPointF(x, 0.0), QPointF(x, h))

        def draw_marker_dot(pt: QPointF, col: QColor) -> None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(col)
            painter.drawEllipse(pt, 4.5, 4.5)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(pt, 2.0, 2.0)

        # 2. Download Marker Dot
        val_down = self._down_history[idx]
        down_ceiling = self._effective_ceiling(self._down_history, self._max_down_bps)
        norm_down = self._compute_normalized_y(val_down, down_ceiling)
        down_y = down_rect.bottom() - (norm_down * (down_rect.height() - 3.0)) - 1.0
        draw_marker_dot(QPointF(x, down_y), down_color)

        # 3. Upload Marker Dot
        val_up = self._up_history[idx]
        up_ceiling = self._effective_ceiling(self._up_history, self._max_up_bps)
        norm_up = self._compute_normalized_y(val_up, up_ceiling)
        up_y = up_rect.bottom() - (norm_up * (up_rect.height() - 3.0)) - 1.0
        draw_marker_dot(QPointF(x, up_y), up_color)

        # 4. Ping & Jitter Marker Dot (if active)
        val_ping = self._ping_history[idx] if idx < len(self._ping_history) else 0.0
        val_jitter = self._jitter_history[idx] if idx < len(self._jitter_history) else 0.0
        is_ping_lost = idx < len(self._ping_loss_history) and self._ping_loss_history[idx]
        if ping_rect is not None and (val_ping > 0 or val_jitter > 0 or is_ping_lost):
            active_pings = [p for p in self._ping_history if p > 0]
            max_ping = max(active_pings) if active_pings else 20.0
            active_jitters = [j for j in self._jitter_history if j > 0]
            max_jitter = max(active_jitters) if active_jitters else 5.0
            ping_ceiling = max(30.0, max(max_ping, max_jitter) * 1.25)

            if is_ping_lost:
                draw_marker_dot(QPointF(x, ping_rect.bottom() - 3.0), QColor("#FF5252"))
            elif val_ping > 0:
                norm_ping = min(1.0, max(0.0, val_ping / ping_ceiling))
                ping_y = ping_rect.bottom() - (norm_ping * (ping_rect.height() - 14.0)) - 1.0
                draw_marker_dot(QPointF(x, ping_y), QColor(self.config.ping_color))

            if val_jitter > 0:
                norm_jitter = min(1.0, max(0.0, val_jitter / ping_ceiling))
                jitter_y = ping_rect.bottom() - (norm_jitter * (ping_rect.height() - 14.0)) - 1.0
                draw_marker_dot(QPointF(x, jitter_y), QColor(self.config.jitter_color))

        # 5. Floating HUD Badge
        count = len(self._down_history)
        age_sec = int(round((count - 1 - idx) * self.config.refresh_interval_sec))
        age_text = "Jetzt • Live" if age_sec == 0 else f"vor {age_sec}s"

        val_pc_down = self._pc_down_history[idx] if idx < len(self._pc_down_history) else 0.0
        val_pc_up = self._pc_up_history[idx] if idx < len(self._pc_up_history) else 0.0
        show_pc = self.config.enable_local_traffic_monitor and (val_pc_down > 0 or val_pc_up > 0)
        show_ping = ping_rect is not None and (val_ping > 0 or val_jitter > 0 or is_ping_lost)

        base_s = max(1.0, self.config.ui_scale)
        badge_w = (185.0 if show_pc else 150.0) * base_s
        line_h = 16.0 * base_s
        pad_x = 8.0 * base_s
        pad_y = 4.0 * base_s
        badge_h = 54.0 * base_s
        if show_pc:
            badge_h += line_h
        if show_ping:
            badge_h += line_h

        if x + 10.0 + badge_w <= w - 4.0:
            badge_x = x + 10.0
        else:
            badge_x = max(4.0, x - 10.0 - badge_w)

        if self._hover_mouse_y is not None:
            badge_y = max(4.0, min(h - badge_h - 4.0, self._hover_mouse_y - (badge_h / 2.0)))
        else:
            badge_y = max(4.0, (h - badge_h) / 2.0)

        badge_rect = QRectF(badge_x, badge_y, badge_w, badge_h)

        # Translucent dark HUD card
        painter.setBrush(QColor(16, 22, 28, 235))
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
        painter.drawRoundedRect(badge_rect, 5.0 * base_s, 5.0 * base_s)

        font_hdr = QFont("Segoe UI", max(7, int(round(8.0 * base_s))), QFont.Weight.Bold)
        font_body = QFont("Segoe UI", max(7, int(round(8.0 * base_s))), QFont.Weight.DemiBold)
        font_sub = QFont("Segoe UI", max(6, int(round(7.0 * base_s))), QFont.Weight.Bold)

        # Header: [vor Xs] or [Jetzt • Live]
        painter.setFont(font_hdr)
        painter.setPen(QColor("#94A3B8"))
        painter.drawText(
            QRectF(badge_x + pad_x, badge_y + pad_y, badge_w - 2 * pad_x, line_h),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"[{age_text}]",
        )

        # Down row
        painter.setFont(font_body)
        painter.setPen(down_color)
        down_str = format_rate(val_down, self.config.show_as_bits)
        painter.drawText(
            QRectF(badge_x + pad_x, badge_y + pad_y + line_h, badge_w - 2 * pad_x, line_h),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"↓ Down:  {down_str}",
        )

        # Up row
        painter.setPen(up_color)
        up_str = format_rate(val_up, self.config.show_as_bits)
        painter.drawText(
            QRectF(badge_x + pad_x, badge_y + pad_y + 2 * line_h, badge_w - 2 * pad_x, line_h),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"↑ Up:      {up_str}",
        )

        curr_y = badge_y + pad_y + 3 * line_h

        # Local PC row (if active)
        if show_pc:
            painter.setFont(font_sub)
            pc_d = format_rate(val_pc_down, self.config.show_as_bits)
            pc_u = format_rate(val_pc_up, self.config.show_as_bits)
            painter.setPen(QColor("#CBD5E1"))
            painter.drawText(
                QRectF(badge_x + pad_x, curr_y, badge_w - 2 * pad_x, line_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"PC:  ↓ {pc_d}  •  ↑ {pc_u}",
            )
            curr_y += line_h

        # Ping & Jitter row (if active)
        if show_ping:
            painter.setFont(font_sub)
            ping_x = badge_x + pad_x
            p_str = "✕ Timeout" if is_ping_lost else f"◆ {val_ping:.1f} ms"
            j_str = f"▲ {val_jitter:.1f} ms"
            w_half = (badge_w - 2 * pad_x) / 2.0
            painter.setPen(QColor("#FF5252") if is_ping_lost else QColor(self.config.ping_color))
            painter.drawText(
                QRectF(ping_x, curr_y, w_half, line_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                p_str,
            )
            painter.setPen(QColor(self.config.jitter_color))
            painter.drawText(
                QRectF(ping_x + w_half, curr_y, w_half, line_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                j_str,
            )

        painter.restore()
