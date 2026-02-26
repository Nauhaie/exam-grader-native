"""Annotation overlay: draw annotation markers on top of the PDF image."""
import math
from typing import List

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygon

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
        _draw_marker(painter, ann, cx, cy, w, h)

    painter.end()
    return result


def _draw_marker(painter: QPainter, ann: Annotation, cx: int, cy: int, w: int, h: int):
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
    elif ann.type == "line" and ann.x2 is not None and ann.y2 is not None:
        pen = QPen(QColor("#1565C0"), 2)
        painter.setPen(pen)
        x2 = int(ann.x2 * w)
        y2 = int(ann.y2 * h)
        painter.drawLine(cx, cy, x2, y2)
    elif ann.type == "arrow" and ann.x2 is not None and ann.y2 is not None:
        pen = QPen(QColor("#1565C0"), 2)
        painter.setPen(pen)
        x2 = int(ann.x2 * w)
        y2 = int(ann.y2 * h)
        _draw_arrow(painter, cx, cy, x2, y2)
    elif ann.type == "circle" and ann.x2 is not None and ann.y2 is not None:
        pen = QPen(QColor("#1565C0"), 2)
        painter.setPen(pen)
        x2 = int(ann.x2 * w)
        y2 = int(ann.y2 * h)
        # cx,cy = center; x2,y2 = point on edge → radius = distance
        radius = int(math.hypot(x2 - cx, y2 - cy))
        painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)


def _draw_arrow(painter: QPainter, x1: int, y1: int, x2: int, y2: int):
    """Draw a line with an arrowhead at (x2, y2)."""
    painter.drawLine(x1, y1, x2, y2)
    if x1 == x2 and y1 == y2:
        return
    angle = math.atan2(y2 - y1, x2 - x1)
    arrow_size = 12
    half_angle = math.pi / 6  # 30°
    pts = QPolygon([
        QPoint(x2, y2),
        QPoint(
            int(x2 - arrow_size * math.cos(angle - half_angle)),
            int(y2 - arrow_size * math.sin(angle - half_angle)),
        ),
        QPoint(
            int(x2 - arrow_size * math.cos(angle + half_angle)),
            int(y2 - arrow_size * math.sin(angle + half_angle)),
        ),
    ])
    old_brush = painter.brush()
    painter.setBrush(QColor("#1565C0"))
    painter.drawPolygon(pts)
    painter.setBrush(old_brush)


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
        if ann.type in ("line", "arrow") and ann.x2 is not None and ann.y2 is not None:
            # Distance from point to line segment
            dist = _point_to_segment_dist(
                px * img_width, py * img_height,
                ann.x * img_width, ann.y * img_height,
                ann.x2 * img_width, ann.y2 * img_height,
            )
            if dist <= tolerance_px:
                return i
        elif ann.type == "circle" and ann.x2 is not None and ann.y2 is not None:
            cx = ann.x * img_width
            cy = ann.y * img_height
            radius = math.hypot((ann.x2 - ann.x) * img_width, (ann.y2 - ann.y) * img_height)
            dist_to_center = math.hypot(px * img_width - cx, py * img_height - cy)
            if abs(dist_to_center - radius) <= tolerance_px:
                return i
        else:
            dx = (ann.x - px) * img_width
            dy = (ann.y - py) * img_height
            if math.hypot(dx, dy) <= tolerance_px:
                return i
    return -1


def _point_to_segment_dist(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Minimum distance from point (px,py) to segment (x1,y1)-(x2,y2)."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
