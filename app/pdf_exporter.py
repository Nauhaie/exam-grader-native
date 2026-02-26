"""Export annotated PDFs by baking annotations into copies of the originals.

Coordinate notes
----------------
PyMuPDF's ``page.rect`` is already **rotation-aware**: for a landscape A3 page
stored with ``/Rotate 90`` the rect reports the wide (landscape) dimensions.
Likewise ``page.draw_*`` methods use those same user-space coordinates.
Fractional annotation coordinates (0.0-1.0) are therefore consistent with
``page.rect.width / height`` for any page orientation.
"""
import math
import os
from typing import Callable, List, Optional

import fitz

from models import Annotation, Student


def export_all(
    students: List[Student],
    exams_dir: str,
    annotations_loader: Callable[[str], List[Annotation]],
    output_dir: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> tuple[int, int]:
    """Bake annotations into each student's PDF and save to *output_dir*.

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
        dst = os.path.join(output_dir, f"{student.student_number}_annotated.pdf")
        bake_annotations(src, anns, dst)
        exported += 1
    if progress_cb:
        progress_cb(total, total)
    return exported, skipped


def bake_annotations(pdf_path: str, annotations: List[Annotation], output_path: str):
    """Open *pdf_path*, draw *annotations* on each page, save to *output_path*.

    Drawing uses ``page.rect`` dimensions which are rotation-aware, so the
    annotation positions are correct for landscape pages too.
    """
    doc = fitz.open(pdf_path)
    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        page_anns = [a for a in annotations if a.page == page_idx]
        if not page_anns:
            continue
        # page.rect is rotation-aware: width/height match the displayed dimensions.
        pw, ph = page.rect.width, page.rect.height
        for ann in page_anns:
            cx, cy = ann.x * pw, ann.y * ph
            if ann.type == "checkmark":
                _draw_checkmark(page, cx, cy)
            elif ann.type == "cross":
                _draw_cross(page, cx, cy)
            elif ann.type == "text" and ann.text:
                _draw_text(page, ann, cx, cy, pw)
            elif ann.type == "line" and ann.x2 is not None and ann.y2 is not None:
                page.draw_line(
                    (cx, cy),
                    (ann.x2 * pw, ann.y2 * ph),
                    color=(0.08, 0.4, 0.75), width=2,
                )
            elif ann.type == "arrow" and ann.x2 is not None and ann.y2 is not None:
                _draw_arrow(page, cx, cy, ann.x2 * pw, ann.y2 * ph)
            elif ann.type == "circle" and ann.x2 is not None and ann.y2 is not None:
                radius = math.hypot(ann.x2 * pw - cx, ann.y2 * ph - cy)
                page.draw_circle(
                    (cx, cy), radius,
                    color=(0.08, 0.4, 0.75), width=2,
                )
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()


# ── Shape helpers ─────────────────────────────────────────────────────────────

def _draw_checkmark(page, cx: float, cy: float, r: float = 12):
    page.draw_line((cx - r, cy), (cx - r / 3, cy + r),
                   color=(0, 0.6, 0), width=2)
    page.draw_line((cx - r / 3, cy + r), (cx + r, cy - r),
                   color=(0, 0.6, 0), width=2)


def _draw_cross(page, cx: float, cy: float, r: float = 12):
    page.draw_line((cx - r, cy - r), (cx + r, cy + r),
                   color=(0.85, 0.1, 0.1), width=2)
    page.draw_line((cx + r, cy - r), (cx - r, cy + r),
                   color=(0.85, 0.1, 0.1), width=2)


def _draw_text(page, ann: Annotation, cx: float, cy: float, pw: float):
    text = ann.text or ""
    if ann.width is not None:
        box_w = max(ann.width * pw, 10)
    else:
        box_w = max(len(text) * 5.5, 20)

    # Estimate lines and height
    chars_per_line = max(1, int(box_w / 5.5))
    line_count = max(1, math.ceil(len(text) / chars_per_line))
    box_h = max(14.0, line_count * 11 + 6)

    rect = fitz.Rect(cx, cy, cx + box_w, cy + box_h)
    page.draw_rect(rect, color=(0, 0, 0), fill=(1, 1, 0.2), width=0.5)
    page.insert_textbox(rect, text, fontsize=9, color=(0, 0, 0), align=0)


def _draw_arrow(page, x1: float, y1: float, x2: float, y2: float):
    page.draw_line((x1, y1), (x2, y2), color=(0.08, 0.4, 0.75), width=2)
    if x1 == x2 and y1 == y2:
        return
    angle = math.atan2(y2 - y1, x2 - x1)
    size, half = 12, math.pi / 6
    pts = [
        fitz.Point(x2, y2),
        fitz.Point(x2 - size * math.cos(angle - half), y2 - size * math.sin(angle - half)),
        fitz.Point(x2 - size * math.cos(angle + half), y2 - size * math.sin(angle + half)),
    ]
    shape = page.new_shape()
    shape.draw_polyline(pts + [pts[0]])   # close by repeating first point
    shape.finish(fill=(0.08, 0.4, 0.75), color=(0.08, 0.4, 0.75), closePath=True)
    shape.commit()
