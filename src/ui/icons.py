"""Vector icon utilities for the Fritz!Box Traffic Widget."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
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
