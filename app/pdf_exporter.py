"""Export annotated PDFs by baking annotations into copies of the originals.

Coordinate notes
----------------
PyMuPDF's ``page.rect`` is rotation-aware: for a landscape A3 page stored
with ``/Rotate 90`` it reports the wide (landscape) dimensions.

However ``page.draw_*`` methods operate in the **native** (pre-rotation) PDF
user-space, not in the visual coordinate space.  We therefore convert visual
fractional annotation coordinates → visual pixels → native draw coordinates
via ``to_draw()`` before calling any draw method.
"""
import math
import os
from typing import Callable, List, Optional, Tuple

import fitz

from models import Annotation, Student


# ── Colour constants ──────────────────────────────────────────────────────────
_RED    = (0.8, 0.08, 0.08)   # lines, arrows, circles
_GREEN  = (0.0, 0.60, 0.0)    # checkmarks
_ORANGE = (1.0, 0.55, 0.0)    # tilde (~)


def export_all(
    students: List[Student],
    exams_dir: str,
    annotations_loader: Callable[[str], List[Annotation]],
    output_dir: str,
    filename_template: str = "{student_number}_annotated",
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> tuple[int, int]:
    """Bake annotations into each student's PDF and save to *output_dir*.

    *filename_template* may reference any field of the student CSV row, e.g.
    ``"Exam1_{participantID}_annotated"``.  Falls back to
    ``"{student_number}_annotated"`` for missing keys.

    Returns *(exported, skipped)* counts.
    """
    os.makedirs(output_dir, exist_ok=True)
    exported = skipped = 0
    total = len(students)
    for i, student in enumerate(students):
        if progress_cb:
            progress_cb(i, total)
        src = os.path.join(exams_dir, f"{student.student_number}.pdf")
        if not os.path.isfile(src):
            skipped += 1
            continue
        anns = annotations_loader(student.student_number)

        # Build output filename from template
        fields = dict(student.extra_fields)
        fields.update(
            student_number=student.student_number,
            last_name=student.last_name,
            first_name=student.first_name,
        )
        try:
            stem = filename_template.format_map(fields)
        except (KeyError, ValueError):
            stem = f"{student.student_number}_annotated"
        dst = os.path.join(output_dir, f"{stem}.pdf")

        bake_annotations(src, anns, dst)
        exported += 1
    if progress_cb:
        progress_cb(total, total)
    return exported, skipped


def bake_annotations(pdf_path: str, annotations: List[Annotation], output_path: str):
    """Open *pdf_path*, draw *annotations* on each page, save to *output_path*."""
    doc = fitz.open(pdf_path)
    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        page_anns = [a for a in annotations if a.page == page_idx]
        if not page_anns:
            continue

        # Visual dimensions (rotation-aware)
        pw, ph = page.rect.width, page.rect.height
        rot = page.rotation
        mw = page.mediabox.width
        mh = page.mediabox.height

        def to_draw(vx: float, vy: float):
            """Convert visual (page.rect) coords to PyMuPDF draw coords."""
            if rot == 90:
                return vy, mh - vx
            if rot == 180:
                return mw - vx, mh - vy
            if rot == 270:
                return mw - vy, vx
            return vx, vy   # rot == 0

        for ann in page_anns:
            cx_v, cy_v = ann.x * pw, ann.y * ph

            if ann.type == "checkmark":
                _draw_checkmark(page, cx_v, cy_v, to_draw)
            elif ann.type == "cross":
                _draw_cross(page, cx_v, cy_v, to_draw)
            elif ann.type == "tilde":
                _draw_tilde(page, cx_v, cy_v, rot, to_draw)
            elif ann.type == "text" and ann.text:
                _draw_text(page, ann, cx_v, cy_v, pw, rot, mw, mh)
            elif ann.type == "line" and ann.x2 is not None and ann.y2 is not None:
                p1 = to_draw(cx_v, cy_v)
                p2 = to_draw(ann.x2 * pw, ann.y2 * ph)
                page.draw_line(p1, p2, color=_RED, width=2)
            elif ann.type == "arrow" and ann.x2 is not None and ann.y2 is not None:
                p1 = to_draw(cx_v, cy_v)
                p2 = to_draw(ann.x2 * pw, ann.y2 * ph)
                _draw_arrow(page, p1[0], p1[1], p2[0], p2[1])
            elif ann.type == "circle" and ann.x2 is not None and ann.y2 is not None:
                cx_d, cy_d = to_draw(cx_v, cy_v)
                ex_d, ey_d = to_draw(ann.x2 * pw, ann.y2 * ph)
                radius = math.hypot(ex_d - cx_d, ey_d - cy_d)
                page.draw_circle((cx_d, cy_d), radius, color=_RED, width=2)

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()


# ── Shape helpers ─────────────────────────────────────────────────────────────

def _draw_checkmark(page, cx_v: float, cy_v: float,
                    to_draw: Callable[[float, float], Tuple[float, float]]):
    r = 6
    p1 = to_draw(cx_v - r,     cy_v)
    p2 = to_draw(cx_v - r / 3, cy_v + r)
    p3 = to_draw(cx_v + r,     cy_v - r)
    page.draw_line(p1, p2, color=_GREEN, width=1.5)
    page.draw_line(p2, p3, color=_GREEN, width=1.5)


def _draw_cross(page, cx_v: float, cy_v: float,
                to_draw: Callable[[float, float], Tuple[float, float]]):
    r = 6
    page.draw_line(to_draw(cx_v - r, cy_v - r), to_draw(cx_v + r, cy_v + r),
                   color=_RED, width=1.5)
    page.draw_line(to_draw(cx_v + r, cy_v - r), to_draw(cx_v - r, cy_v + r),
                   color=_RED, width=1.5)


def _draw_tilde(page, cx_v: float, cy_v: float, rot: int,
                to_draw: Callable[[float, float], Tuple[float, float]]):
    cx_d, cy_d = to_draw(cx_v, cy_v)
    # rotate= undoes the page rotation so the glyph appears upright
    page.insert_text(
        fitz.Point(cx_d - 4, cy_d + 5),
        "~", fontsize=14, color=_ORANGE, rotate=rot,
    )


_TEXT_PAD_PT = 3   # matches _TEXT_PAD in annotation_overlay.py


def _draw_text(page, ann: Annotation, cx_v: float, cy_v: float,
               pw: float, rot: int, mw: float, mh: float):
    text = ann.text or ""
    if ann.width is not None:
        box_w = max(ann.width * pw, 10)
    else:
        box_w = max(len(text) * 5.5, 20)

    # Estimate height (respecting explicit newlines)
    chars_per_line = max(1, int(box_w / 5.5))
    explicit_lines = text.split("\n")
    wrapped = sum(
        max(1, math.ceil(len(ln) / chars_per_line)) if ln else 1
        for ln in explicit_lines
    )
    p = _TEXT_PAD_PT
    box_h = max(14.0, wrapped * 11 + p * 2)

    box_rect  = _text_rect(cx_v,     cy_v,     box_w,         box_h,         rot, mw, mh)
    text_rect = _text_rect(cx_v + p, cy_v + p, max(1.0, box_w - p * 2),
                                                max(1.0, box_h - p * 2), rot, mw, mh)
    page.draw_rect(box_rect, color=(0, 0, 0), fill=(1, 1, 0.2), width=0.5)
    page.insert_textbox(text_rect, text, fontsize=9, color=(0, 0, 0), align=0,
                        rotate=rot if rot in (90, 180, 270) else 0)


def _text_rect(cx_v: float, cy_v: float, bw: float, bh: float,
               rot: int, mw: float, mh: float) -> fitz.Rect:
    """Map a visual text box top-left + size to a native draw-space Rect."""
    if rot == 0:
        return fitz.Rect(cx_v, cy_v, cx_v + bw, cy_v + bh)
    if rot == 90:
        return fitz.Rect(cy_v, mh - cx_v - bw, cy_v + bh, mh - cx_v)
    if rot == 180:
        return fitz.Rect(mw - cx_v - bw, mh - cy_v - bh, mw - cx_v, mh - cy_v)
    # rot == 270
    return fitz.Rect(mw - cy_v - bh, cx_v, mw - cy_v, cx_v + bw)


def _draw_arrow(page, x1: float, y1: float, x2: float, y2: float):
    """Draw a line with a filled arrowhead at (x2, y2) – coords in draw space."""
    page.draw_line((x1, y1), (x2, y2), color=_RED, width=2)
    if x1 == x2 and y1 == y2:
        return
    angle = math.atan2(y2 - y1, x2 - x1)
    size, half = 12, math.pi / 6
    pts = [
        fitz.Point(x2, y2),
        fitz.Point(x2 - size * math.cos(angle - half),
                   y2 - size * math.sin(angle - half)),
        fitz.Point(x2 - size * math.cos(angle + half),
                   y2 - size * math.sin(angle + half)),
    ]
    shape = page.new_shape()
    shape.draw_polyline(pts + [pts[0]])
    shape.finish(fill=_RED, color=_RED, closePath=True)
    shape.commit()
