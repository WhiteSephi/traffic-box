"""Vector icon utilities for the Fritz!Box Traffic Widget."""

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
    """Generate clean monochrome vector icons for UI buttons (graph, counters, settings).

    :param icon_type: 'graph', 'counters', or 'settings'.
    :param color: Hex string or QColor for the icon stroke/fill.
    :param size: Dimension in pixels.
    :return: Transparent QPixmap.
    """
    col = QColor(color) if isinstance(color, str) else color
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

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
        cx = size / 2.0
        cy = size / 2.0
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
