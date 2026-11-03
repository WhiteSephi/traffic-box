"""System Tray icon and shared context menu for the Fritz!Box Traffic Widget."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPolygonF, QPixmap
from PySide6.QtWidgets import QWidget


def create_router_icon(is_connected: bool = True) -> QIcon:
    """Create a crisp programmatic router & arrows icon for tray and header."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Router body
    body_rect = QRectF(8, 34, 48, 20)
    painter.setBrush(QColor("#2B343B"))
    painter.setPen(QPen(QColor("#8C96A0"), 2.5))
    painter.drawRoundedRect(body_rect, 6, 6)

    # Status LEDs
    led_color = QColor("#00E676") if is_connected else QColor("#FF5252")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(led_color)
    painter.drawEllipse(QPointF(20, 44), 3.5, 3.5)
    painter.setBrush(QColor("#FFEA00"))
    painter.drawEllipse(QPointF(31, 44), 3.0, 3.0)
    painter.setBrush(QColor("#4A5CFF"))
    painter.drawEllipse(QPointF(42, 44), 3.0, 3.0)

    # Down arrow (yellow, left)
    painter.setBrush(QColor("#FFEA00"))
    down_poly = QPolygonF(
        [
            QPointF(20, 6),
            QPointF(26, 6),
            QPointF(26, 18),
            QPointF(31, 18),
            QPointF(23, 28),
            QPointF(15, 18),
            QPointF(20, 18),
        ]
    )
    painter.drawPolygon(down_poly)

    # Up arrow (blue, right)
    painter.setBrush(QColor("#4A5CFF"))
    up_poly = QPolygonF(
        [
            QPointF(41, 6),
            QPointF(49, 16),
            QPointF(44, 16),
            QPointF(44, 28),
            QPointF(38, 28),
            QPointF(38, 16),
            QPointF(33, 16),
        ]
    )
    painter.drawPolygon(up_poly)

    painter.end()
    return QIcon(pix)
