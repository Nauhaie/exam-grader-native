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
from dataclasses import replace
from typing import Callable, List, Optional, Tuple

import fitz

from models import Annotation, GradingScheme, GradingSettings, Student


# ── Colour constants ──────────────────────────────────────────────────────────
_RED    = (0.8, 0.08, 0.08)   # lines, arrows, circles
_GREEN  = (0.0, 0.60, 0.0)    # checkmarks
_ORANGE = (1.0, 0.55, 0.0)    # tilde (~)
_BLACK  = (0, 0, 0)
_GREY   = (0.35, 0.35, 0.35)


# ── Cover page ────────────────────────────────────────────────────────────────

def _insert_cover_page(
    doc: fitz.Document,
    student: Student,
    grades: dict,
    scheme: GradingScheme,
    settings: GradingSettings,
) -> None:
    """Insert a cover page at position 0 with student info and grade breakdown.

    The cover page has the same aspect ratio as page 1 of the scan.
    """
    # Determine aspect ratio from the first page (if any)
    if doc.page_count > 0:
        first = doc[0]
        pw, ph = first.rect.width, first.rect.height
    else:
        pw, ph = 595.0, 842.0  # A4 portrait default

    # Insert a blank page at index 0
    page = doc.new_page(pno=0, width=pw, height=ph)

    # Resolve effective score_total
    scheme_total = scheme.max_total()
    score_total = settings.score_total if settings.score_total is not None else scheme_total
    if score_total <= 0:
        score_total = max(scheme_total, 1.0)

    student_scores = grades or {}
    points_total = sum(v for v in student_scores.values() if v is not None)

    # Compute mark (same formula as the grading panel)
    rounding = max(0.001, settings.rounding)
    raw_mark = (points_total / score_total) * settings.max_note if score_total else 0.0
    mark = round(raw_mark / rounding) * rounding

    # ── Layout constants ──────────────────────────────────────────────────
    margin = pw * 0.08
    cx = pw / 2              # horizontal centre
    y = margin               # running y position
    fs_title = min(pw, ph) * 0.028     # slightly smaller for name+ID line
    fs_mark = min(pw, ph) * 0.04       # smaller grade
    fs_body = min(pw, ph) * 0.018      # ~15 pt on A4
    fs_small = min(pw, ph) * 0.016     # ~11 pt on A4
    line_gap = fs_body * 1.6

    # ── Student name + ID (same line) ────────────────────────────────────
    name_text = f"{student.first_name} {student.last_name} ({student.student_number})"
    _centered_text(page, name_text, cx, y, pw - 2 * margin, fs_title, bold=True)
    y += fs_title * 2.0

    # ── Mark ──────────────────────────────────────────────────────────────
    mark_str = f"{mark:g}/{settings.max_note:g}"
    _centered_text(page, mark_str, cx, y, pw - 2 * margin, fs_mark, bold=True)
    y += fs_mark * 1.6

    # ── Total points ──────────────────────────────────────────────────────
    _centered_text(page, f"Total: {points_total:g}/{score_total:g} pts",
                   cx, y, pw - 2 * margin, fs_body, color=_GREY)
    y += fs_body * 2.5

    # ── Separator line ────────────────────────────────────────────────────
    page.draw_line((margin, y), (pw - margin, y), color=_GREY, width=0.5)
    y += line_gap

    # ── Exercise / subquestion breakdown ──────────────────────────────────
    col_name_x = margin
    col_score_x = pw - margin
    usable_w = pw - 2 * margin

    for ex in scheme.exercises:
        # Exercise total
        ex_max = sum(sq.max_points for sq in ex.subquestions)
        ex_pts = sum(student_scores.get(sq.name, 0) or 0 for sq in ex.subquestions)

        if settings.cover_page_detail and ex.subquestions:
            # Compact: exercise name + total in bold, then subquestion scores in normal weight
            parts = [f"{sq.name}: {(student_scores.get(sq.name, 0) or 0):g}/{sq.max_points:g}"
                     for sq in ex.subquestions]
            ex_prefix = f"{ex.name}:  {ex_pts:g}/{ex_max:g}"
            detail_str = "  (" + ", ".join(parts) + ")"
            # Measure the bold prefix width so the detail part starts right after it
            try:
                bold_font = fitz.Font("hebo")
                prefix_w = bold_font.text_length(ex_prefix, fontsize=fs_small)
            except Exception:
                prefix_w = len(ex_prefix) * fs_small * 0.5
            _left_text(page, ex_prefix, col_name_x, y, usable_w, fs_small, bold=True)
            _left_text(page, detail_str, col_name_x + prefix_w, y,
                       max(1.0, usable_w - prefix_w), fs_small)
        else:
            # Exercise header line only
            ex_label = f"{ex.name}:  {ex_pts:g}/{ex_max:g}"
            _left_text(page, ex_label, col_name_x, y, usable_w, fs_body, bold=True)
        y += line_gap

        # Avoid running past the bottom of the page
        if y > ph - margin:
            break


def _centered_text(page, text: str, cx: float, y: float, max_w: float,
                   fontsize: float, bold: bool = False, color=_BLACK):
    """Insert centred text on *page* at vertical position *y*."""
    fname = "hebo" if bold else "helv"
    rect = fitz.Rect(cx - max_w / 2, y, cx + max_w / 2, y + fontsize * 2)
    page.insert_textbox(rect, text, fontsize=fontsize, fontname=fname,
                        color=color, align=1)  # align=1 → centre


def _left_text(page, text: str, x: float, y: float, max_w: float,
               fontsize: float, bold: bool = False, color=_BLACK):
    fname = "hebo" if bold else "helv"
    rect = fitz.Rect(x, y, x + max_w, y + fontsize * 2)
    page.insert_textbox(rect, text, fontsize=fontsize, fontname=fname,
                        color=color, align=0)  # align=0 → left


def bake_annotations(pdf_path: str, annotations: List[Annotation], output_path: str,
                     log_path: Optional[str] = None, debug: bool = False,
                     student: Optional[Student] = None,
                     grades: Optional[dict] = None,
                     scheme: Optional[GradingScheme] = None,
                     settings: Optional[GradingSettings] = None):
    """Open *pdf_path*, draw *annotations* on each page, save to *output_path*.

    If *student*, *grades*, *scheme*, and *settings* are all provided, a cover
    page with the student's name, mark, and grade breakdown is inserted before
    the scanned pages.

    If *log_path* is given and *debug* is True, write a human-readable debug log
    alongside the PDF with full coordinate details for every annotation so issues
    can be diagnosed.  When *debug* is False, no terminal output and no log file
    are produced.
    """
    # Open the log file first so partial output is preserved on any crash.
    _log_fh = None
    if debug and log_path:
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
        if debug:
            print(f"[bake] source  : {pdf_path}")
            print(f"[bake] output  : {output_path}")
            print(f"[bake] annotations: {len(annotations)}")
        _log(f"SOURCE : {pdf_path}")
        _log(f"OUTPUT : {output_path}")
        _log(f"ANNOTATIONS : {len(annotations)}")
        _log("")

        try:
            if debug:
                print("[bake] opening PDF…")
            doc = fitz.open(pdf_path)
            try:
                # ── Insert cover page (before annotating) ─────────────────
                cover_inserted = False
                if student is not None and grades is not None and scheme is not None and settings is not None:
                    _insert_cover_page(doc, student, grades, scheme, settings)
                    cover_inserted = True
                    _log("COVER PAGE inserted at page 0")
                    if debug:
                        print("[bake] cover page inserted at page 0")
                    # Shift annotation page indices since we prepended a page
                    annotations = [replace(a, page=a.page + 1) for a in annotations]

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

                    # ── Annotations ─────────────────────────────────────────
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
                            # Height is always computed from content; never stored.
                            box_h = max(measured_box_h, 10.0)
                            box_rect  = _text_rect(cx_v,     cy_v,     box_w,         box_h,         rot, mw, mh)
                            text_rect = _text_rect(cx_v + p, cy_v + p, max(1.0, box_w - p * 2),
                                                                        max(1.0, box_h - p * 2), rot, mw, mh)
                            text_rotate = rot
                            _log(f"       text   : {ann.text!r}")
                            _log(f"       ann.width={ann.width}")
                            _log(f"       box_w={box_w:.2f}  box_h={box_h:.2f}  (PDF pts)")
                            _log(f"       box_rect  : {box_rect}")
                            _log(f"       text_rect : {text_rect}")
                            _log(f"       text_rotate (insert_textbox rotate=) : {text_rotate}")
                            _draw_text(page, ann, cx_v, cy_v, pw, ph, rot, mw, mh)
                        elif ann.type == "line" and ann.x2 is not None and ann.y2 is not None:
                            p1 = to_draw(cx_v, cy_v)
                            p2 = to_draw(ann.x2 * pw, ann.y2 * ph)
                            _log(f"       draw_line : {p1} → {p2}")
                            page.draw_line(p1, p2, color=_RED, width=2, lineCap=1,
                                           stroke_opacity=0.8)
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
                            page.draw_circle((cx_d, cy_d), radius, color=_RED, width=2, stroke_opacity=0.8)
                        elif ann.type == "rectcross" and ann.x2 is not None and ann.y2 is not None:
                            p1 = to_draw(cx_v, cy_v)
                            p2 = to_draw(ann.x2 * pw, ann.y2 * ph)
                            p3 = to_draw(ann.x2 * pw, cy_v)
                            p4 = to_draw(cx_v, ann.y2 * ph)
                            _log(f"       draw_rectcross : {p1}→{p2}, {p3}→{p4}")
                            page.draw_line(p1, p2, color=_RED, width=2.5, lineCap=1,
                                           stroke_opacity=0.8)
                            page.draw_line(p3, p4, color=_RED, width=2.5, lineCap=1,
                                           stroke_opacity=0.8)

                    _log("")

                # Try garbage=0 first (plain save, no object restructuring) to
                # avoid "MuPDF error: format error: object is not a stream" which
                # is triggered by the cross-reference rebuild done at higher levels.
                # Fall back to garbage=4 for a full cleanup pass if level 0 fails.
                save_ok = False
                for garbage_level in (0, 4):
                    try:
                        if debug:
                            print(f"[bake] saving with garbage={garbage_level}…")
                        doc.save(output_path, garbage=garbage_level, deflate=True)
                        save_ok = True
                        if debug:
                            print(f"[bake] save OK (garbage={garbage_level})")
                        _log(f"SAVE OK (garbage={garbage_level})")
                        break
                    except Exception as exc:
                        if debug:
                            print(f"[bake] save FAILED (garbage={garbage_level}): {exc}")
                        _log(f"SAVE FAILED (garbage={garbage_level}): {exc}")
                if not save_ok:
                    if debug:
                        print("[bake] ERROR: PDF could not be saved – all garbage levels failed.")
                    _log("ERROR: PDF could not be saved – all garbage levels failed.")
            finally:
                doc.close()
        except Exception as exc:
            if debug:
                print(f"[bake] FATAL ERROR opening PDF: {exc}")
            _log(f"FATAL ERROR opening PDF: {exc}")
    finally:
        if _log_fh:
            _log_fh.close()
            if debug:
                print(f"[bake] log file closed: {log_path}")


# ── Shape helpers ─────────────────────────────────────────────────────────────

def _draw_checkmark(page, cx_v: float, cy_v: float,
                    to_draw: Callable[[float, float], Tuple[float, float]]):
    r = 6
    p1 = to_draw(cx_v - r,     cy_v)
    p2 = to_draw(cx_v - r / 3, cy_v + r)
    p3 = to_draw(cx_v + r,     cy_v - r)
    shape = page.new_shape()
    shape.draw_polyline([p1, p2, p3])
    shape.finish(color=_GREEN, width=2.5, lineCap=1, lineJoin=1,
                 closePath=False, stroke_opacity=0.8)
    shape.commit()


def _draw_cross(page, cx_v: float, cy_v: float,
                to_draw: Callable[[float, float], Tuple[float, float]]):
    r = 6
    page.draw_line(to_draw(cx_v - r, cy_v - r), to_draw(cx_v + r, cy_v + r),
                   color=_RED, width=2.5, lineCap=1, stroke_opacity=0.8)
    page.draw_line(to_draw(cx_v + r, cy_v - r), to_draw(cx_v - r, cy_v + r),
                   color=_RED, width=2.5, lineCap=1, stroke_opacity=0.8)


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
    shape.finish(color=_ORANGE, width=2.5, lineCap=1, lineJoin=1,
                 closePath=False, stroke_opacity=0.8)
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

    # Height is always computed from content; never stored.
    _, measured_box_h = _measure_text_box(text, box_w, p, _TEXT_FONTSIZE)
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
    page.draw_line((x1, y1), (x2, y2), color=_RED, width=2, lineCap=1, stroke_opacity=0.8)
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
    shape.finish(fill=_RED, color=_RED, closePath=True, fill_opacity=0.8, stroke_opacity=0.8)
    shape.commit()
