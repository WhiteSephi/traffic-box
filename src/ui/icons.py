"""Vector icon utilities for the TrafficBox Widget."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap


def create_arrow_pixmap(
    color: str | QColor,
    direction: str = "down",
    size: int = 12,
) -> QPixmap:
    """Generate a crisp, antialiased monochrome vector arrow icon in the specified color.

    :param color: Hex string or QColor for the arrow fill.
    :param direction: 'down' for download, 'up' for upload.
    :param size: Dimension in pixels (width == height).
    :return: Transparent QPixmap with the rendered arrow.
    """
    col = QColor(color) if isinstance(color, str) else color
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(col)

    cx = size / 2.0
    cy = size / 2.0
    half_head = max(2.8, size * 0.32)
    stem_half = max(0.9, size * 0.11)
    pad = 1.5

    path = QPainterPath()
    if direction.lower() == "down":
        # Tip points down
        path.moveTo(cx, size - pad)
        path.lineTo(cx - half_head, cy)
        path.lineTo(cx - stem_half, cy)
        path.lineTo(cx - stem_half, pad)
        path.lineTo(cx + stem_half, pad)
        path.lineTo(cx + stem_half, cy)
        path.lineTo(cx + half_head, cy)
        path.closeSubpath()
    else:
        # Tip points up
        path.moveTo(cx, pad)
        path.lineTo(cx - half_head, cy)
        path.lineTo(cx - stem_half, cy)
        path.lineTo(cx - stem_half, size - pad)
        path.lineTo(cx + stem_half, size - pad)
        path.lineTo(cx + stem_half, cy)
        path.lineTo(cx + half_head, cy)
        path.closeSubpath()

    painter.drawPath(path)
    painter.end()
    return pix


def create_ui_icon(
    icon_type: str,
    color: str | QColor,
    size: int = 14,
) -> QPixmap:
    """Generate clean monochrome vector icons for UI buttons (graph, counters, settings, github).

    :param icon_type: 'graph', 'counters', 'settings', or 'github'.
    :param color: Hex string or QColor for the icon stroke/fill.
    :param size: Dimension in pixels.
    :return: Transparent QPixmap.
    """
    col = QColor(color) if isinstance(color, str) else color
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if icon_type == "github":
        scale = size / 24.0
        painter.scale(scale, scale)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(col)
        # Standard GitHub Octocat mark in 24x24 viewBox
        gh = QPainterPath()
        gh.moveTo(12.0, 0.5)
        gh.cubicTo(5.65, 0.5, 0.5, 5.65, 0.5, 12.0)
        gh.cubicTo(0.5, 17.08, 3.79, 21.39, 8.36, 22.91)
        gh.cubicTo(8.94, 23.02, 9.15, 22.66, 9.15, 22.36)
        gh.cubicTo(9.15, 22.09, 9.14, 21.37, 9.13, 20.42)
        gh.cubicTo(5.94, 21.11, 5.27, 18.88, 5.27, 18.88)
        gh.cubicTo(4.75, 17.55, 4.0, 17.2, 4.0, 17.2)
        gh.cubicTo(2.96, 16.49, 4.08, 16.5, 4.08, 16.5)
        gh.cubicTo(5.23, 16.58, 5.84, 17.68, 5.84, 17.68)
        gh.cubicTo(6.86, 19.44, 8.53, 18.93, 9.18, 18.64)
        gh.cubicTo(9.28, 17.9, 9.58, 17.39, 9.91, 17.1)
        gh.cubicTo(7.36, 16.81, 4.68, 15.82, 4.68, 11.42)
        gh.cubicTo(4.68, 10.17, 5.13, 9.15, 5.86, 8.35)
        gh.cubicTo(5.74, 8.06, 5.35, 6.89, 5.97, 5.31)
        gh.cubicTo(5.97, 5.31, 6.93, 5.0, 9.13, 6.49)
        gh.cubicTo(10.05, 6.23, 11.03, 6.11, 12.0, 6.1)
        gh.cubicTo(12.97, 6.11, 13.95, 6.23, 14.87, 6.49)
        gh.cubicTo(17.07, 5.0, 18.03, 5.31, 18.03, 5.31)
        gh.cubicTo(18.65, 6.89, 18.26, 8.06, 18.14, 8.35)
        gh.cubicTo(18.87, 9.15, 19.32, 10.17, 19.32, 11.42)
        gh.cubicTo(19.32, 15.83, 16.63, 16.81, 14.07, 17.09)
        gh.cubicTo(14.48, 17.45, 14.85, 18.15, 14.85, 19.23)
        gh.cubicTo(14.85, 20.77, 14.84, 22.02, 14.84, 22.36)
        gh.cubicTo(14.84, 22.67, 15.05, 23.03, 15.63, 22.91)
        gh.cubicTo(20.21, 21.39, 23.5, 17.08, 23.5, 12.0)
        gh.cubicTo(23.5, 5.65, 18.35, 0.5, 12.0, 0.5)
        gh.closeSubpath()
        painter.drawPath(gh)
        painter.end()
        return pix

    # Reference coordinate system is 14x14 so icons scale crisply to any pixel size
    scale = size / 14.0
    painter.scale(scale, scale)

    if icon_type == "graph":
        pen = painter.pen()
        pen.setColor(col)
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(1, 10, 3, 10)
        painter.drawLine(3, 10, 6, 4)
        painter.drawLine(6, 4, 9, 11)
        painter.drawLine(9, 11, 11, 2)
        painter.drawLine(11, 2, 13, 7)
    elif icon_type == "counters":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(col)
        painter.drawRoundedRect(QRectF(1.5, 7.0, 2.8, 6.0), 1.0, 1.0)
        painter.drawRoundedRect(QRectF(5.6, 2.5, 2.8, 10.5), 1.0, 1.0)
        painter.drawRoundedRect(QRectF(9.7, 5.0, 2.8, 8.0), 1.0, 1.0)
    elif icon_type == "settings":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(col)
        cx = 7.0
        cy = 7.0
        r_out = 5.8
        r_in = 4.3
        r_hole = 1.8
        path = QPainterPath()
        teeth = 6
        for i in range(teeth):
            angle = i * (2.0 * math.pi / teeth)
            half_step = math.pi / teeth
            a1 = angle - half_step * 0.35
            a2 = angle + half_step * 0.35
            a3 = angle + half_step * 0.70
            a4 = angle + half_step * 1.30
            if i == 0:
                path.moveTo(cx + r_out * math.cos(a1), cy + r_out * math.sin(a1))
            else:
                path.lineTo(cx + r_out * math.cos(a1), cy + r_out * math.sin(a1))
            path.lineTo(cx + r_out * math.cos(a2), cy + r_out * math.sin(a2))
            path.lineTo(cx + r_in * math.cos(a3), cy + r_in * math.sin(a3))
            path.lineTo(cx + r_in * math.cos(a4), cy + r_in * math.sin(a4))
        path.closeSubpath()
        hole = QPainterPath()
        hole.addEllipse(QPointF(cx, cy), r_hole, r_hole)
        path = path.subtracted(hole)
        painter.drawPath(path)

    painter.end()
    return pix
