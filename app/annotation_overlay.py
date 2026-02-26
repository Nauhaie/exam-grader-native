"""Annotation overlay: draw annotation markers on top of the PDF image."""
from typing import List

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

from models import Annotation

MARKER_RADIUS = 12


def draw_annotations(pixmap: QPixmap, annotations: List[Annotation], page: int) -> QPixmap:
    """Return a copy of pixmap with annotations for the given page drawn on it."""
    result = pixmap.copy()
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    w = result.width()
    h = result.height()

    for ann in annotations:
        if ann.page != page:
            continue
        cx = int(ann.x * w)
        cy = int(ann.y * h)
        _draw_marker(painter, ann, cx, cy)

    painter.end()
    return result


def _draw_marker(painter: QPainter, ann: Annotation, cx: int, cy: int):
    r = MARKER_RADIUS
    if ann.type == "checkmark":
        pen = QPen(QColor("green"), 3)
        painter.setPen(pen)
        # Draw ✓ shape: two lines
        painter.drawLine(cx - r, cy, cx - r // 3, cy + r)
        painter.drawLine(cx - r // 3, cy + r, cx + r, cy - r)
    elif ann.type == "cross":
        pen = QPen(QColor("red"), 3)
        painter.setPen(pen)
        painter.drawLine(cx - r, cy - r, cx + r, cy + r)
        painter.drawLine(cx + r, cy - r, cx - r, cy + r)
    elif ann.type == "text" and ann.text:
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        text_rect = fm.boundingRect(ann.text)
        padding = 3
        bg_rect = QRect(
            cx,
            cy - text_rect.height() - padding,
            text_rect.width() + padding * 2,
            text_rect.height() + padding * 2,
        )
        painter.fillRect(bg_rect, QColor(255, 255, 0, 200))
        pen = QPen(QColor("black"), 1)
        painter.setPen(pen)
        painter.drawRect(bg_rect)
        painter.drawText(
            QPoint(cx + padding, cy),
            ann.text,
        )


def find_annotation_at(
    annotations: List[Annotation],
    page: int,
    px: float,  # fractional x
    py: float,  # fractional y
    img_width: int,
    img_height: int,
    tolerance_px: int = 20,
) -> int:
    """Return index of annotation near (px, py) on given page, or -1."""
    for i, ann in enumerate(annotations):
        if ann.page != page:
            continue
        dx = (ann.x - px) * img_width
        dy = (ann.y - py) * img_height
        if (dx * dx + dy * dy) ** 0.5 <= tolerance_px:
            return i
    return -1
