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

        log_path = os.path.join(output_dir, f"{stem}.log")
        bake_annotations(src, anns, dst, log_path=log_path)
        exported += 1
    if progress_cb:
        progress_cb(total, total)
    return exported, skipped


def bake_annotations(pdf_path: str, annotations: List[Annotation], output_path: str,
                     log_path: Optional[str] = None):
    """Open *pdf_path*, draw *annotations* on each page, save to *output_path*.

    If *log_path* is given, write a human-readable debug log alongside the PDF
    with full coordinate details for every annotation so issues can be diagnosed.
    The log file is opened immediately and flushed after every entry so that a
    partial log is preserved even if the process crashes during save.
    """
    # Open the log file first so partial output is preserved on any crash.
    _log_fh = None
    if log_path:
        try:
            _log_fh = open(log_path, "w", encoding="utf-8")
            print(f"[bake] log file opened: {log_path}")
        except OSError as e:
            print(f"[bake] WARNING: could not open log file {log_path!r}: {e}")
            _log_fh = None

    def _log(msg: str) -> None:
        if _log_fh:
            _log_fh.write(msg + "\n")
            _log_fh.flush()

    try:
        print(f"[bake] source  : {pdf_path}")
        print(f"[bake] output  : {output_path}")
        print(f"[bake] annotations: {len(annotations)}")
        _log(f"SOURCE : {pdf_path}")
        _log(f"OUTPUT : {output_path}")
        _log(f"ANNOTATIONS : {len(annotations)}")
        _log("")

        try:
            print("[bake] opening PDF…")
            doc = fitz.open(pdf_path)
            try:
                for page_idx in range(doc.page_count):
                    page = doc[page_idx]

                    # Visual dimensions (rotation-aware)
                    pw, ph = page.rect.width, page.rect.height
                    rot = page.rotation
                    mw = page.mediabox.width
                    mh = page.mediabox.height

                    _log(f"=== PAGE {page_idx} ===")
                    _log(f"  rotation       : {rot} deg")
                    _log(f"  page.rect      : w={pw:.2f}  h={ph:.2f}  (visual/rotation-aware)")
                    _log(f"  mediabox       : w={mw:.2f}  h={mh:.2f}  (native PDF units)")

                    def to_draw(vx: float, vy: float):
                        """Convert visual (page.rect) coords to PyMuPDF draw coords."""
                        if rot == 90:
                            return vy, mh - vx
                        if rot == 180:
                            return mw - vx, mh - vy
                        if rot == 270:
                            return mw - vy, vx
                        return vx, vy   # rot == 0

                    # ── "MARKED" watermark at top-left of every page ──────────────
                    # insert_textbox rotate= must equal the page rotation so that the
                    # text baseline goes left-to-right in the viewer (rot=0 → 0,
                    # rot=90 → 90, etc.).  Using (360-rot) produced upside-down text
                    # on landscape pages because it reversed the character direction.
                    marked_fontsize = 8
                    marked_rect = _text_rect(4, 4, 50, 16, rot, mw, mh)
                    marked_rotate = rot
                    overflow = page.insert_textbox(
                        marked_rect, "MARKED",
                        fontsize=marked_fontsize, fontname="helv",
                        color=(0.8, 0.0, 0.0), align=0, rotate=marked_rotate,
                    )
                    _log(
                        f"  MARKED stamp   : insert_textbox rect={marked_rect}"
                        f" rotate={marked_rotate} overflow={overflow:.2f}"
                    )

                    page_anns = [a for a in annotations if a.page == page_idx]
                    _log(f"  annotations    : {len(page_anns)}")

                    for ann_i, ann in enumerate(page_anns):
                        cx_v, cy_v = ann.x * pw, ann.y * ph
                        _log(f"  -- ann[{ann_i}] type={ann.type!r}")
                        _log(f"       frac   x={ann.x:.4f}  y={ann.y:.4f}")
                        _log(f"       visual x={cx_v:.2f}  y={cy_v:.2f}  (pw={pw:.2f} ph={ph:.2f})")

                        if ann.type == "checkmark":
                            _draw_checkmark(page, cx_v, cy_v, to_draw)
                        elif ann.type == "cross":
                            _draw_cross(page, cx_v, cy_v, to_draw)
                        elif ann.type == "tilde":
                            _draw_tilde(page, cx_v, cy_v, rot, to_draw)
                        elif ann.type == "text" and ann.text:
                            p = _TEXT_PAD_PT
                            if ann.width is not None:
                                box_w = max(ann.width * pw, 10.0)
                            else:
                                try:
                                    font = fitz.Font("helv")
                                    lines = ann.text.split("\n") if ann.text else [""]
                                    box_w = max(
                                        (font.text_length(ln, fontsize=_TEXT_FONTSIZE) for ln in lines),
                                        default=0.0,
                                    ) + p * 2
                                except Exception:
                                    box_w = max(len(ann.text) * 5.5, 20.0)
                                box_w = max(box_w, 20.0)
                            _, measured_box_h = _measure_text_box(ann.text, box_w, p, _TEXT_FONTSIZE)
                            if ann.height is not None:
                                box_h = max(ann.height * ph, measured_box_h, 10.0)
                            else:
                                box_h = max(measured_box_h, 10.0)
                            box_rect  = _text_rect(cx_v,     cy_v,     box_w,         box_h,         rot, mw, mh)
                            text_rect = _text_rect(cx_v + p, cy_v + p, max(1.0, box_w - p * 2),
                                                                        max(1.0, box_h - p * 2), rot, mw, mh)
                            text_rotate = rot
                            _log(f"       text   : {ann.text!r}")
                            _log(f"       ann.width={ann.width}  ann.height={ann.height}")
                            _log(f"       box_w={box_w:.2f}  box_h={box_h:.2f}  (PDF pts, measured_box_h={measured_box_h:.2f})")
                            _log(f"       box_rect  : {box_rect}")
                            _log(f"       text_rect : {text_rect}")
                            _log(f"       text_rotate (insert_textbox rotate=) : {text_rotate}")
                            _draw_text(page, ann, cx_v, cy_v, pw, ph, rot, mw, mh)
                        elif ann.type == "line" and ann.x2 is not None and ann.y2 is not None:
                            p1 = to_draw(cx_v, cy_v)
                            p2 = to_draw(ann.x2 * pw, ann.y2 * ph)
                            _log(f"       draw_line : {p1} → {p2}")
                            page.draw_line(p1, p2, color=_RED, width=2)
                        elif ann.type == "arrow" and ann.x2 is not None and ann.y2 is not None:
                            p1 = to_draw(cx_v, cy_v)
                            p2 = to_draw(ann.x2 * pw, ann.y2 * ph)
                            _log(f"       draw_arrow : {p1} → {p2}")
                            _draw_arrow(page, p1[0], p1[1], p2[0], p2[1])
                        elif ann.type == "circle" and ann.x2 is not None and ann.y2 is not None:
                            cx_d, cy_d = to_draw(cx_v, cy_v)
                            ex_d, ey_d = to_draw(ann.x2 * pw, ann.y2 * ph)
                            radius = math.hypot(ex_d - cx_d, ey_d - cy_d)
                            _log(f"       draw_circle : center=({cx_d:.2f},{cy_d:.2f}) radius={radius:.2f}")
                            page.draw_circle((cx_d, cy_d), radius, color=_RED, width=2)

                    _log("")

                # Try garbage=0 first (plain save, no object restructuring) to
                # avoid "MuPDF error: format error: object is not a stream" which
                # is triggered by the cross-reference rebuild done at higher levels.
                # Fall back to garbage=4 for a full cleanup pass if level 0 fails.
                save_ok = False
                for garbage_level in (0, 4):
                    try:
                        print(f"[bake] saving with garbage={garbage_level}…")
                        doc.save(output_path, garbage=garbage_level, deflate=True)
                        save_ok = True
                        print(f"[bake] save OK (garbage={garbage_level})")
                        _log(f"SAVE OK (garbage={garbage_level})")
                        break
                    except Exception as exc:
                        print(f"[bake] save FAILED (garbage={garbage_level}): {exc}")
                        _log(f"SAVE FAILED (garbage={garbage_level}): {exc}")
                if not save_ok:
                    print("[bake] ERROR: PDF could not be saved – all garbage levels failed.")
                    _log("ERROR: PDF could not be saved – all garbage levels failed.")
            finally:
                doc.close()
        except Exception as exc:
            print(f"[bake] FATAL ERROR opening PDF: {exc}")
            _log(f"FATAL ERROR opening PDF: {exc}")
    finally:
        if _log_fh:
            _log_fh.close()
            print(f"[bake] log file closed: {log_path}")


# ── Shape helpers ─────────────────────────────────────────────────────────────

def _draw_checkmark(page, cx_v: float, cy_v: float,
                    to_draw: Callable[[float, float], Tuple[float, float]]):
    r = 6
    p1 = to_draw(cx_v - r,     cy_v)
    p2 = to_draw(cx_v - r / 3, cy_v + r)
    p3 = to_draw(cx_v + r,     cy_v - r)
    page.draw_line(p1, p2, color=_GREEN, width=2.5)
    page.draw_line(p2, p3, color=_GREEN, width=2.5)


def _draw_cross(page, cx_v: float, cy_v: float,
                to_draw: Callable[[float, float], Tuple[float, float]]):
    r = 6
    page.draw_line(to_draw(cx_v - r, cy_v - r), to_draw(cx_v + r, cy_v + r),
                   color=_RED, width=2.5)
    page.draw_line(to_draw(cx_v + r, cy_v - r), to_draw(cx_v - r, cy_v + r),
                   color=_RED, width=2.5)


def _draw_tilde(page, cx_v: float, cy_v: float, rot: int,
                to_draw: Callable[[float, float], Tuple[float, float]]):
    # Draw a smooth S-curve wave (same shape as the screen renderer).
    amp = 5    # amplitude in visual pts
    ww  = 18   # half-width on each side of centre
    p0  = to_draw(cx_v - ww,     cy_v)
    cp1 = to_draw(cx_v - ww / 2, cy_v - amp)
    cp2 = to_draw(cx_v,          cy_v - amp)
    p1  = to_draw(cx_v,          cy_v)
    cp3 = to_draw(cx_v,          cy_v + amp)
    cp4 = to_draw(cx_v + ww / 2, cy_v + amp)
    p2  = to_draw(cx_v + ww,     cy_v)
    shape = page.new_shape()
    shape.draw_bezier(p0, cp1, cp2, p1)
    shape.draw_bezier(p1, cp3, cp4, p2)
    shape.finish(color=_ORANGE, width=2.5, closePath=False)
    shape.commit()


_TEXT_PAD_PT = 3   # matches _TEXT_PAD in annotation_overlay.py
_TEXT_FONTSIZE = 9


def _measure_text_box(text: str, box_w: float, p: float = _TEXT_PAD_PT,
                      fontsize: float = _TEXT_FONTSIZE) -> Tuple[float, float]:
    """Return *(box_w, box_h)* in PDF points sufficient to hold *text*.

    Uses PyMuPDF's own font metrics so the result matches ``insert_textbox``
    exactly (no more yellow boxes with missing text).

    The formula is derived from insert_textbox internals:
      required_height = n_lines * line_h + |descender| * fontsize
    where line_h = fontsize * (ascender - descender).
    """
    inner_w = max(1.0, box_w - p * 2)
    try:
        font = fitz.Font("helv")
        # Per-line height used by insert_textbox (ascender + |descender|)
        line_h = fontsize * (font.ascender - font.descender)
        # One-time bottom-of-last-line overhead (= |descender| * fontsize)
        extra_h = fontsize * abs(font.descender)
        total_lines = 0
        for para in text.split("\n"):
            words = para.split() if para.strip() else []
            if not words:
                total_lines += 1
                continue
            cur_w = 0.0
            n_lines = 1
            for word in words:
                ww = font.text_length(word + " ", fontsize=fontsize)
                if cur_w > 0 and cur_w + ww > inner_w:
                    n_lines += 1
                    cur_w = ww
                else:
                    cur_w += ww
            total_lines += n_lines
        box_h = max(20.0, total_lines * line_h + extra_h + p * 2)
    except Exception:
        # Fallback: approximate ascender+descender ratio for a typical font
        # (1.374 actual) plus per-line bottom padding (~0.3), giving ~1.7.
        total_lines = max(1, len(text.split("\n")))
        box_h = max(20.0, total_lines * fontsize * 1.7 + p * 2)
    return box_w, box_h


def _draw_text(page, ann: Annotation, cx_v: float, cy_v: float,
               pw: float, ph: float, rot: int, mw: float, mh: float):
    text = ann.text or ""
    p = _TEXT_PAD_PT
    if ann.width is not None:
        box_w = max(ann.width * pw, 10.0)
    else:
        # Compute width from the longest line using actual font metrics.
        try:
            font = fitz.Font("helv")
            lines = text.split("\n") if text else [""]
            box_w = max(
                (font.text_length(ln, fontsize=_TEXT_FONTSIZE) for ln in lines),
                default=0.0,
            ) + p * 2
        except Exception:
            box_w = max(len(text) * 5.5, 20.0)
        box_w = max(box_w, 20.0)

    # Always measure the minimum height required to fit the text at this width.
    # If a stored height (from the inline editor) is smaller than the measured
    # minimum, the text won't fit inside insert_textbox and will be invisible.
    # Using max() ensures the box is always tall enough to show the text while
    # still respecting the user's sizing when it is larger.
    _, measured_box_h = _measure_text_box(text, box_w, p, _TEXT_FONTSIZE)
    if ann.height is not None:
        box_h = max(ann.height * ph, measured_box_h, 10.0)
    else:
        box_h = max(measured_box_h, 10.0)

    box_rect  = _text_rect(cx_v,     cy_v,     box_w,         box_h,         rot, mw, mh)
    text_rect = _text_rect(cx_v + p, cy_v + p, max(1.0, box_w - p * 2),
                                                max(1.0, box_h - p * 2), rot, mw, mh)

    # Draw the yellow background in its own shape so that its fill_opacity does
    # NOT carry over into the text rendering (which caused invisible text).
    bg = page.new_shape()
    bg.draw_rect(box_rect)
    bg.finish(color=(0, 0, 0), fill=(1, 1, 0), fill_opacity=0.5, width=0.5)
    bg.commit()

    # Insert text directly on the page so it is always drawn fully opaque black.
    # Using page.insert_textbox (rather than Shape) avoids subtle state issues
    # that can cause text to silently disappear in some PyMuPDF versions.
    # rotate= must equal the page rotation so characters advance left-to-right
    # in the viewer.  Using (360-rot) reversed the direction and produced
    # upside-down text on landscape (rot=90/270) pages.
    text_rotate = rot
    overflow = page.insert_textbox(text_rect, text, fontsize=_TEXT_FONTSIZE,
                                   fontname="helv", color=(0, 0, 0),
                                   align=0, rotate=text_rotate)
    if overflow < 0:
        # Text still did not fit (e.g. word-wrap produced more lines than
        # measured_box_h estimated).  Re-measure without the stored-height
        # constraint and retry with the freshly computed rect.
        _, fallback_h = _measure_text_box(text, box_w, p, _TEXT_FONTSIZE)
        fallback_rect = _text_rect(cx_v + p, cy_v + p, max(1.0, box_w - p * 2),
                                   max(1.0, fallback_h - p * 2), rot, mw, mh)
        page.insert_textbox(fallback_rect, text, fontsize=_TEXT_FONTSIZE,
                            fontname="helv", color=(0, 0, 0),
                            align=0, rotate=text_rotate)


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
