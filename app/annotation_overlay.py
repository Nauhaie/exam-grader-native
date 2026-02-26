"""Annotation overlay: draw annotation markers on top of the PDF image.

All public helpers that deal with pixel positions accept *img_width* and
*img_height* which are the **rendered** pixmap dimensions.  Because PyMuPDF
returns page.rect already rotation-aware, those pixel dimensions are always
consistent with the fractional (0.0-1.0) annotation coordinates regardless of
whether the page is portrait or landscape.
"""
import math
from typing import List, Optional, Tuple

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap, QPolygon,
)

from models import Annotation

MARKER_RADIUS = 12
_TEXT_FONT_PT = 9
_TEXT_PAD = 3
_RESIZE_HANDLE = 8          # side length (px) of the resize-handle square
_TEXT_WRAP_MAX_H = 10_000   # generous max-height for word-wrap bound calculation


# ── Public drawing helpers ────────────────────────────────────────────────────

def draw_annotations(pixmap: QPixmap, annotations: List[Annotation], page: int) -> QPixmap:
    """Return a *copy* of *pixmap* with all annotations for *page* drawn on it."""
    result = pixmap.copy()
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    w, h = result.width(), result.height()
    for ann in annotations:
        if ann.page != page:
            continue
        _draw_one(painter, ann, int(ann.x * w), int(ann.y * h), w, h)
    painter.end()
    return result


def draw_preview(
    pixmap: QPixmap,
    tool: str,
    start: Tuple[float, float],
    end: Tuple[float, float],
) -> None:
    """Draw a dashed ghost shape on *pixmap* **in place** (modifies the pixmap)."""
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    w, h = pixmap.width(), pixmap.height()
    x1, y1 = int(start[0] * w), int(start[1] * h)
    x2, y2 = int(end[0] * w), int(end[1] * h)

    pen = QPen(QColor("#1565C0"), 2, Qt.PenStyle.DashLine)
    painter.setPen(pen)
    if tool == "line":
        painter.drawLine(x1, y1, x2, y2)
    elif tool == "arrow":
        _draw_arrow(painter, x1, y1, x2, y2)
    elif tool == "circle":
        radius = int(math.hypot(x2 - x1, y2 - y1))
        if radius > 0:
            painter.drawEllipse(x1 - radius, y1 - radius, radius * 2, radius * 2)

    # Start-point dot
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#1565C0"))
    painter.drawEllipse(x1 - 4, y1 - 4, 8, 8)
    painter.end()


def get_text_box_rect(ann: Annotation, img_width: int, img_height: int) -> Optional[QRect]:
    """Return the pixel bounding-box of a text annotation, or *None*."""
    if ann.type != "text" or not ann.text:
        return None
    cx = int(ann.x * img_width)
    cy = int(ann.y * img_height)
    bw, bh = _text_box_size(ann.text, ann.width, img_width)
    return QRect(cx, cy, bw, bh)


def find_annotation_at(
    annotations: List[Annotation],
    page: int,
    px: float,
    py: float,
    img_width: int,
    img_height: int,
    tolerance_px: int = 20,
) -> int:
    """Return the index of the annotation nearest to *(px, py)* on *page*, or -1."""
    for i, ann in enumerate(annotations):
        if ann.page != page:
            continue
        if ann.type in ("line", "arrow") and ann.x2 is not None and ann.y2 is not None:
            dist = _pt_seg_dist(
                px * img_width, py * img_height,
                ann.x * img_width, ann.y * img_height,
                ann.x2 * img_width, ann.y2 * img_height,
            )
            if dist <= tolerance_px:
                return i
        elif ann.type == "circle" and ann.x2 is not None and ann.y2 is not None:
            cx = ann.x * img_width
            cy = ann.y * img_height
            radius = math.hypot(
                (ann.x2 - ann.x) * img_width,
                (ann.y2 - ann.y) * img_height,
            )
            dist = math.hypot(px * img_width - cx, py * img_height - cy)
            if abs(dist - radius) <= tolerance_px:
                return i
        elif ann.type == "text" and ann.text:
            rect = get_text_box_rect(ann, img_width, img_height)
            if rect and rect.contains(int(px * img_width), int(py * img_height)):
                return i
        else:
            dx = (ann.x - px) * img_width
            dy = (ann.y - py) * img_height
            if math.hypot(dx, dy) <= tolerance_px:
                return i
    return -1


# ── Internal helpers ──────────────────────────────────────────────────────────

def _text_box_size(text: str, width_frac: Optional[float], img_width: int) -> Tuple[int, int]:
    """Return *(width_px, height_px)* for a text annotation box."""
    font = QFont()
    font.setPointSize(_TEXT_FONT_PT)
    font.setBold(True)
    fm = QFontMetrics(font)
    p = _TEXT_PAD

    if width_frac is not None:
        bw = max(int(width_frac * img_width), 20)
    else:
        lines = text.split("\n") if text else [""]
        bw = max((fm.horizontalAdvance(ln) for ln in lines), default=0) + p * 2
        bw = max(bw, 20)

    inner = QRect(0, 0, bw - p * 2, _TEXT_WRAP_MAX_H)
    bound = fm.boundingRect(inner, Qt.TextFlag.TextWordWrap, text)
    bh = bound.height() + p * 2
    return bw, bh


def _draw_one(painter: QPainter, ann: Annotation, cx: int, cy: int, w: int, h: int):
    r = MARKER_RADIUS
    if ann.type == "checkmark":
        painter.setPen(QPen(QColor("green"), 3))
        painter.drawLine(cx - r, cy, cx - r // 3, cy + r)
        painter.drawLine(cx - r // 3, cy + r, cx + r, cy - r)

    elif ann.type == "cross":
        painter.setPen(QPen(QColor("red"), 3))
        painter.drawLine(cx - r, cy - r, cx + r, cy + r)
        painter.drawLine(cx + r, cy - r, cx - r, cy + r)

    elif ann.type == "text" and ann.text:
        font = QFont()
        font.setPointSize(_TEXT_FONT_PT)
        font.setBold(True)
        painter.setFont(font)
        p = _TEXT_PAD
        bw, bh = _text_box_size(ann.text, ann.width, w)
        bg = QRect(cx, cy, bw, bh)
        painter.fillRect(bg, QColor(255, 255, 0, 200))
        painter.setPen(QPen(QColor("black"), 1))
        painter.drawRect(bg)
        painter.drawText(QRect(cx + p, cy + p, bw - p * 2, bh - p * 2),
                         Qt.TextFlag.TextWordWrap, ann.text)
        # Resize handle: small blue square at the bottom-right corner
        hs = _RESIZE_HANDLE
        painter.fillRect(cx + bw - hs, cy + bh - hs, hs, hs, QColor(70, 130, 230, 200))

    elif ann.type == "line" and ann.x2 is not None and ann.y2 is not None:
        painter.setPen(QPen(QColor("#1565C0"), 2))
        painter.drawLine(cx, cy, int(ann.x2 * w), int(ann.y2 * h))

    elif ann.type == "arrow" and ann.x2 is not None and ann.y2 is not None:
        painter.setPen(QPen(QColor("#1565C0"), 2))
        _draw_arrow(painter, cx, cy, int(ann.x2 * w), int(ann.y2 * h))

    elif ann.type == "circle" and ann.x2 is not None and ann.y2 is not None:
        painter.setPen(QPen(QColor("#1565C0"), 2))
        radius = int(math.hypot(ann.x2 * w - cx, ann.y2 * h - cy))
        painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)


def _draw_arrow(painter: QPainter, x1: int, y1: int, x2: int, y2: int):
    """Draw a line with a filled arrowhead at *(x2, y2)*."""
    painter.drawLine(x1, y1, x2, y2)
    if x1 == x2 and y1 == y2:
        return
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 12
    half = math.pi / 6
    pts = QPolygon([
        QPoint(x2, y2),
        QPoint(int(x2 - size * math.cos(angle - half)),
               int(y2 - size * math.sin(angle - half))),
        QPoint(int(x2 - size * math.cos(angle + half)),
               int(y2 - size * math.sin(angle + half))),
    ])
    old_brush = painter.brush()
    painter.setBrush(QColor("#1565C0"))
    painter.drawPolygon(pts)
    painter.setBrush(old_brush)


def _pt_seg_dist(px: float, py: float,
                 x1: float, y1: float, x2: float, y2: float) -> float:
    """Minimum distance from point *(px, py)* to segment *(x1,y1)-(x2,y2)*."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


# Keep the old name as an alias so nothing breaks
_point_to_segment_dist = _pt_seg_dist
