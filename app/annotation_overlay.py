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
    QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QPolygon,
)

from models import Annotation

MARKER_RADIUS = 12          # pt at zoom 1 (≈ 4 mm on A4 long side)
_CHECKMARK_RADIUS = 6       # half of MARKER_RADIUS — checkmarks/crosses are smaller
_TEXT_FONT_PT = 9
_TEXT_PAD = 3
_RESIZE_HANDLE = 8          # side length (pt) of the resize-handle square
_TEXT_WRAP_MAX_H = 10_000   # generous max-height for word-wrap bound calculation

_RED    = QColor(204, 20, 20)    # colour for lines, arrows, circles
_ORANGE = QColor(255, 140, 0)    # colour for tilde (~) annotation

# Long side of A4 in PDF points (= pixels at 72 dpi, zoom 1.0).
# Used as the reference length so annotation sizes are physically consistent
# for both A4-portrait and A3-landscape pages (both have the same 842 pt height).
BASE_PAGE_HEIGHT: float = 842.0


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
    s = h / BASE_PAGE_HEIGHT
    x1, y1 = int(start[0] * w), int(start[1] * h)
    x2, y2 = int(end[0] * w), int(end[1] * h)

    pen_w = max(1, round(2 * s))
    pen = QPen(_RED, pen_w, Qt.PenStyle.DashLine)
    painter.setPen(pen)
    if tool == "line":
        painter.drawLine(x1, y1, x2, y2)
    elif tool == "arrow":
        _draw_arrow(painter, x1, y1, x2, y2, s)
    elif tool == "circle":
        radius = int(math.hypot(x2 - x1, y2 - y1))
        if radius > 0:
            painter.drawEllipse(x1 - radius, y1 - radius, radius * 2, radius * 2)

    # Start-point dot
    dot_r = max(2, round(4 * s))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_RED)
    painter.drawEllipse(x1 - dot_r, y1 - dot_r, dot_r * 2, dot_r * 2)
    painter.end()


def get_text_box_rect(ann: Annotation, img_width: int, img_height: int) -> Optional[QRect]:
    """Return the pixel bounding-box of a text annotation, or *None*."""
    if ann.type != "text" or not ann.text:
        return None
    cx = int(ann.x * img_width)
    cy = int(ann.y * img_height)
    bw, bh = _text_box_size(ann.text, ann.width, img_width, img_height)
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

def _text_box_size(text: str, width_frac: Optional[float],
                   img_width: int, img_height: int) -> Tuple[int, int]:
    """Return *(width_px, height_px)* for a text annotation box.

    All sizes scale with *img_height* so the box appears the same physical
    size relative to the page regardless of zoom level.
    """
    s = img_height / BASE_PAGE_HEIGHT
    font = QFont()
    font.setPointSize(max(4, round(_TEXT_FONT_PT * s)))
    font.setBold(True)
    fm = QFontMetrics(font)
    p = max(1, round(_TEXT_PAD * s))

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
    s = h / BASE_PAGE_HEIGHT          # scale factor relative to A4 long side
    rc = max(2, round(_CHECKMARK_RADIUS * s))  # radius for checkmark / cross
    stroke = max(1, round(2 * s))     # general pen width
    thick = max(1, round(2 * s))      # pen width for checkmark / cross

    if ann.type == "checkmark":
        painter.setPen(QPen(QColor("green"), thick))
        painter.drawLine(cx - rc, cy, cx - rc // 3, cy + rc)
        painter.drawLine(cx - rc // 3, cy + rc, cx + rc, cy - rc)

    elif ann.type == "cross":
        painter.setPen(QPen(QColor("red"), thick))
        painter.drawLine(cx - rc, cy - rc, cx + rc, cy + rc)
        painter.drawLine(cx + rc, cy - rc, cx - rc, cy + rc)

    elif ann.type == "tilde":
        amp = max(3, round(5 * s))          # wave amplitude (px)
        ww  = max(20, round(36 * s))        # total wave width (px)
        pen_w = max(2, round(3 * s))
        painter.setPen(QPen(_ORANGE, pen_w, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath()
        # S-curve: left-centre → up arc → centre → down arc → right-centre
        path.moveTo(cx - ww // 2, cy)
        path.cubicTo(cx - ww // 4, cy - amp,
                     cx,           cy - amp,
                     cx,           cy)
        path.cubicTo(cx,           cy + amp,
                     cx + ww // 4, cy + amp,
                     cx + ww // 2, cy)
        painter.drawPath(path)

    elif ann.type == "text" and ann.text:
        font = QFont()
        font.setPointSize(max(4, round(_TEXT_FONT_PT * s)))
        font.setBold(True)
        painter.setFont(font)
        p = max(1, round(_TEXT_PAD * s))
        bw, bh = _text_box_size(ann.text, ann.width, w, h)
        bg = QRect(cx, cy, bw, bh)
        painter.fillRect(bg, QColor(255, 255, 0, 128))
        painter.setPen(QPen(QColor("black"), 1))
        painter.drawRect(bg)
        painter.drawText(QRect(cx + p, cy + p, bw - p * 2, bh - p * 2),
                         Qt.TextFlag.TextWordWrap, ann.text)
        # Resize handle: small blue square at the bottom-right corner
        hs = max(4, round(_RESIZE_HANDLE * s))
        painter.fillRect(cx + bw - hs, cy + bh - hs, hs, hs, QColor(70, 130, 230, 200))

    elif ann.type == "line" and ann.x2 is not None and ann.y2 is not None:
        painter.setPen(QPen(_RED, stroke))
        painter.drawLine(cx, cy, int(ann.x2 * w), int(ann.y2 * h))

    elif ann.type == "arrow" and ann.x2 is not None and ann.y2 is not None:
        painter.setPen(QPen(_RED, stroke))
        _draw_arrow(painter, cx, cy, int(ann.x2 * w), int(ann.y2 * h), s)

    elif ann.type == "circle" and ann.x2 is not None and ann.y2 is not None:
        painter.setPen(QPen(_RED, stroke))
        radius = int(math.hypot(ann.x2 * w - cx, ann.y2 * h - cy))
        painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)


def _draw_arrow(painter: QPainter, x1: int, y1: int, x2: int, y2: int,
                scale: float = 1.0):
    """Draw a line with a filled arrowhead at *(x2, y2)*."""
    painter.drawLine(x1, y1, x2, y2)
    if x1 == x2 and y1 == y2:
        return
    angle = math.atan2(y2 - y1, x2 - x1)
    size = max(4, round(MARKER_RADIUS * scale))
    half = math.pi / 6
    pts = QPolygon([
        QPoint(x2, y2),
        QPoint(int(x2 - size * math.cos(angle - half)),
               int(y2 - size * math.sin(angle - half))),
        QPoint(int(x2 - size * math.cos(angle + half)),
               int(y2 - size * math.sin(angle + half))),
    ])
    old_brush = painter.brush()
    painter.setBrush(_RED)
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
