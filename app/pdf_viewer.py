"""Center panel: PDF viewer with annotation support."""
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import fitz  # pymupdf
from PySide6.QtCore import QObject, QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

import annotation_overlay
import data_store
from models import Annotation

TOOL_NONE      = None
TOOL_CHECKMARK = "checkmark"
TOOL_CROSS     = "cross"
TOOL_TEXT      = "text"
TOOL_LINE      = "line"
TOOL_ARROW     = "arrow"
TOOL_CIRCLE    = "circle"
TOOL_TILDE     = "tilde"
TOOL_ERASER    = "eraser"
TOOL_STAMP     = "stamp"
TOOL_RECTCROSS = "rectcross"

_KEY_TOOL_MAP = {
    Qt.Key.Key_V: TOOL_CHECKMARK,
    Qt.Key.Key_X: TOOL_CROSS,
    Qt.Key.Key_T: TOOL_TEXT,
    Qt.Key.Key_L: TOOL_LINE,
    Qt.Key.Key_A: TOOL_ARROW,
    Qt.Key.Key_O: TOOL_CIRCLE,
    Qt.Key.Key_N: TOOL_TILDE,
    Qt.Key.Key_E: TOOL_ERASER,
    Qt.Key.Key_S: TOOL_STAMP,
    Qt.Key.Key_R: TOOL_RECTCROSS,
}

_DRAG_TOL = 20          # pixel hit-tolerance for drag handles
_WHEEL_ZOOM_DIVISOR = 800.0  # wheel-delta units that equal a 1× zoom step
# Pan modifier: Cmd on macOS (MetaModifier maps to Cmd), Ctrl on Win/Linux
_PAN_MOD = Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.ControlModifier

_INLINE_EDITOR_MIN_W  = 120
_INLINE_EDITOR_WIDTH  = 200


def _pm_logical_size(pm: Optional[QPixmap]) -> Tuple[int, int]:
    """Return *(width, height)* of *pm* in device-independent (logical) pixels."""
    if pm and not pm.isNull():
        dpr = pm.devicePixelRatio()
        return int(pm.width() / dpr), int(pm.height() / dpr)
    return 1, 1


@dataclass
class _DragState:
    kind: str        # 'point'|'line-start'|'line-end'|'line-move'|
                     # 'circle-edge'|'circle-move'|'text-resize'
    index: int       # index in _annotations
    start_fx: float
    start_fy: float
    orig_x: float
    orig_y: float
    orig_x2: float = 0.0
    orig_y2: float = 0.0
    orig_width: float = 0.0


class InlineTextEdit(QPlainTextEdit):
    """Floating multi-line editor for text annotations.

    * Enter inserts a newline.
    * Ctrl+Enter (or Ctrl+Return) commits the text.
    * Escape cancels without saving.
    * Clicking away (focusOut) commits non-empty text.
    """

    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, font_pt: int = 9, parent=None):
        super().__init__(parent)
        self._done = False
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Set font explicitly so document layout and fontMetrics() use the
        # correct size (stylesheet alone does not update the document font).
        _font = QFont()
        _font.setPointSize(font_pt)
        _font.setBold(True)
        self.setFont(_font)
        self.document().setDefaultFont(_font)
        self.setStyleSheet(
            "QPlainTextEdit { background-color: #ffff99; border: 1px solid #888;"
            " padding: 1px; }"
        )
        self.document().contentsChanged.connect(self._adjust_height)

    def _adjust_height(self):
        """Resize widget height to match document content (no scrollbars).

        Uses QFontMetrics.boundingRect with word-wrap to compute the exact
        height needed, accounting for document margins so that wrapping aligns
        with the actual QPlainTextEdit layout.
        """
        text = self.toPlainText() or ""
        margins = self.contentsMargins()
        frame = self.frameWidth() * 2
        doc_margin = int(self.document().documentMargin())
        extra_h = frame + margins.top() + margins.bottom() + 2 * doc_margin
        inner_w = max(1, self.width() - frame - margins.left() - margins.right()
                       - 2 * doc_margin)

        fm = self.fontMetrics()
        if text:
            bound = fm.boundingRect(
                QRect(0, 0, inner_w, annotation_overlay._TEXT_WRAP_MAX_H),
                Qt.TextFlag.TextWordWrap,
                text,
            )
            doc_h = bound.height()
        else:
            doc_h = fm.height()

        new_h = max(fm.height() + extra_h, doc_h + extra_h)
        if self.height() != new_h:
            self.resize(self.width(), new_h)
            self.ensureCursorVisible()

    def resizeEvent(self, event):
        """Re-check height when the width changes (word-wrap reflow)."""
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self._adjust_height()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if not self._done:
                self._done = True
                self.cancelled.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                # Ctrl+Enter → commit
                if not self._done:
                    self._done = True
                    self.committed.emit(self.toPlainText())
            else:
                super().keyPressEvent(event)   # plain Enter → newline
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        if not self._done:
            self._done = True
            text = self.toPlainText()
            if text.strip():
                self.committed.emit(text)
            else:
                self.cancelled.emit()
        super().focusOutEvent(event)


class _ToolShortcutFilter(QObject):
    """App-level event filter: tool shortcuts, page/student navigation."""

    def __init__(self, viewer: "PDFViewerPanel", parent=None):
        super().__init__(parent)
        self._viewer = viewer

    def _mouse_over_pdf(self) -> bool:
        """Return True when the mouse pointer is currently over the PDF scroll area."""
        scroll = self._viewer._scroll
        top_left = scroll.mapToGlobal(scroll.rect().topLeft())
        global_rect = QRect(top_left, scroll.size())
        return global_rect.contains(QCursor.pos())

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.KeyPress:
            return False
        # Don't steal keys while any text-input widget has focus
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QPlainTextEdit)):
            return False

        key  = event.key()
        # Mask out non-standard modifiers (e.g. KeypadModifier,
        # GroupSwitchModifier) so comparisons are robust across platforms.
        _RELEVANT = (Qt.KeyboardModifier.ShiftModifier
                     | Qt.KeyboardModifier.ControlModifier
                     | Qt.KeyboardModifier.AltModifier
                     | Qt.KeyboardModifier.MetaModifier)
        mods  = event.modifiers() & _RELEVANT
        alt   = Qt.KeyboardModifier.AltModifier
        shift = Qt.KeyboardModifier.ShiftModifier

        # ── Tool toggles ──────────────────────────────────────────────────────
        if not mods and key in _KEY_TOOL_MAP:
            tool = _KEY_TOOL_MAP[key]
            new = TOOL_NONE if self._viewer._active_tool == tool else tool
            self._viewer.set_active_tool(new)
            return True

        # ── Jump to grading cell ──────────────────────────────────────────────
        if not mods and key == Qt.Key.Key_P:
            self._viewer.jump_requested.emit()
            return True

        # ── Escape: cancel in-progress line / deselect tool ───────────────────
        if not mods and key == Qt.Key.Key_Escape:
            if self._viewer._line_start is not None:
                self._viewer._line_start = None
                self._viewer._preview_pos = None
                self._viewer._update_display()
            else:
                self._viewer.deselect_tool()
            return True

        # ── Shift+Alt+Left / Shift+Alt+Right → previous / next student ────────
        # (checked before Alt-only so Shift+Alt is not consumed by the Alt check)
        if mods == (shift | alt) and key == Qt.Key.Key_Left:
            self._viewer.student_prev_requested.emit()
            return True
        if mods == (shift | alt) and key == Qt.Key.Key_Right:
            self._viewer.student_next_requested.emit()
            return True

        # ── Alt+Left / Alt+Right → previous / next page ───────────────────────
        if mods == alt and key == Qt.Key.Key_Left:
            self._viewer.prev_page()
            return True
        if mods == alt and key == Qt.Key.Key_Right:
            self._viewer.next_page()
            return True

        # ── Plain Left / Right → navigate page when pointer is over the PDF
        #    view AND the page fits entirely (no scrollbars in either direction).
        if not mods and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            if self._mouse_over_pdf():
                hbar = self._viewer._scroll.horizontalScrollBar()
                vbar = self._viewer._scroll.verticalScrollBar()
                if hbar.maximum() == 0 and vbar.maximum() == 0:
                    if key == Qt.Key.Key_Left:
                        self._viewer.prev_page()
                    else:
                        self._viewer.next_page()
                    return True
            return False

        return False


class ClickableLabel(QLabel):
    """QLabel that emits fractional-coordinate mouse signals."""

    pressed       = Signal(float, float)
    moved         = Signal(float, float)
    released      = Signal(float, float)
    double_clicked = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

    def _frac(self, event) -> Tuple[float, float]:
        w, h = self.width(), self.height()
        if w > 0 and h > 0:
            return (
                max(0.0, min(1.0, event.position().x() / w)),
                max(0.0, min(1.0, event.position().y() / h)),
            )
        return 0.0, 0.0

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            fx, fy = self._frac(event)
            self.pressed.emit(fx, fy)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        fx, fy = self._frac(event)
        self.moved.emit(fx, fy)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            fx, fy = self._frac(event)
            self.released.emit(fx, fy)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            fx, fy = self._frac(event)
            self.double_clicked.emit(fx, fy)
        super().mouseDoubleClickEvent(event)


class PDFViewerPanel(QWidget):
    annotations_changed    = Signal()
    jump_requested         = Signal()   # 'P' key
    student_prev_requested = Signal()   # Shift+Alt+Left
    student_next_requested = Signal()   # Shift+Alt+Right
    open_settings_presets_requested = Signal()  # from stamp popup "Edit Presets…"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pdf_path: Optional[str] = None
        self._doc: Optional[fitz.Document] = None
        self._current_page: int = 0
        self._zoom: float = 1.2
        self._annotations: List[Annotation] = []
        self._active_tool: Optional[str] = TOOL_NONE
        self._line_start: Optional[Tuple[float, float]] = None
        self._preview_pos: Optional[Tuple[float, float]] = None
        self._inline_editor: Optional[InlineTextEdit] = None
        self._raw_pixmap: Optional[QPixmap] = None   # PDF page, no annotations
        self._base_pixmap: Optional[QPixmap] = None  # PDF page + baked annotations
        self._drag: Optional[_DragState] = None
        self._drag_moved: bool = False
        # Pan-by-drag state (Cmd/Ctrl + left-drag)
        self._pan_origin: Optional[Tuple[int, int]] = None
        self._pan_hval: int = 0
        self._pan_vval: int = 0
        self._preset_annotations: List[str] = []
        self._stamp_popup: Optional[QWidget] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = QWidget()
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(4, 4, 4, 4)

        self._tool_buttons: Dict[str, QPushButton] = {}
        for tool_id, label, tip in [
            (TOOL_CHECKMARK, "✓", "Checkmark (V)"),
            (TOOL_CROSS,     "✗", "Cross (X)"),
            (TOOL_TEXT,      "T", "Text (T)"),
            (TOOL_LINE,      "╱", "Line (L)"),
            (TOOL_ARROW,     "→", "Arrow (A)"),
            (TOOL_CIRCLE,    "○", "Circle (O)"),
            (TOOL_TILDE,     "~", "Approx/tilde (N)"),
            (TOOL_RECTCROSS, "⊠", "Rect cross (R)"),
            (TOOL_STAMP,     "S", "Stamp preset text (S)"),
            (TOOL_ERASER,    "⌫", "Eraser (E)"),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setFixedWidth(36)
            btn.clicked.connect(lambda checked, t=tool_id: self._on_tool_clicked(t, checked))
            tb.addWidget(btn)
            self._tool_buttons[tool_id] = btn

        tb.addStretch()

        # ── Page navigation (in toolbar) ──────────────────────────────────────
        self._prev_btn = QPushButton("◀")
        self._prev_btn.setToolTip("Previous page")
        self._prev_btn.setFixedWidth(32)
        self._prev_btn.clicked.connect(self._prev_page)
        tb.addWidget(self._prev_btn)

        self._page_counter = QLabel("Page 1 / 1")
        self._page_counter.setFixedWidth(80)
        self._page_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tb.addWidget(self._page_counter)

        self._next_btn = QPushButton("▶")
        self._next_btn.setToolTip("Next page")
        self._next_btn.setFixedWidth(32)
        self._next_btn.clicked.connect(self._next_page)
        tb.addWidget(self._next_btn)

        tb.addStretch()

        # ── Zoom controls (in toolbar) ────────────────────────────────────────
        for label, tip, slot in [
            ("−", "Zoom out", self._zoom_out),
            ("+", "Zoom in",  self._zoom_in),
        ]:
            b = QPushButton(label)
            b.setFixedWidth(32)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            if label == "−":
                tb.addWidget(b)
                self._zoom_label = QLabel("120%")
                self._zoom_label.setFixedWidth(50)
                self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                tb.addWidget(self._zoom_label)
            else:
                tb.addWidget(b)

        layout.addWidget(toolbar)

        # ── Scroll area ───────────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidgetResizable(False)

        self._page_label = ClickableLabel()
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.pressed.connect(self._on_page_pressed)
        self._page_label.moved.connect(self._on_page_moved)
        self._page_label.released.connect(self._on_page_released)
        self._page_label.double_clicked.connect(self._on_page_double_clicked)
        self._scroll.setWidget(self._page_label)
        layout.addWidget(self._scroll, stretch=1)

        # Intercept wheel and native pinch gestures on the scroll viewport
        # so they zoom the PDF instead of scrolling.
        self._scroll.viewport().installEventFilter(self)

        self._show_placeholder()

        self._shortcut_filter = _ToolShortcutFilter(self)
        QApplication.instance().installEventFilter(self._shortcut_filter)

    # ── Public API ────────────────────────────────────────────────────────────

    def load_pdf(self, pdf_path: Optional[str], annotations: List[Annotation]):
        if self._doc:
            self._doc.close()
            self._doc = None
        self._annotations = annotations
        self._current_page = 0
        self._line_start = None
        self._preview_pos = None
        self._drag = None
        self._cancel_inline_editor()
        self._close_stamp_popup()
        if pdf_path and os.path.isfile(pdf_path):
            self._pdf_path = pdf_path
            self._doc = fitz.open(pdf_path)
            data_store.dbg(f"PDF loaded: {pdf_path} ({self._doc.page_count} page(s))")
            self._render_page()
        else:
            self._pdf_path = None
            data_store.dbg(f"PDF not found or no path given: {pdf_path}")
            self._show_placeholder()

    def set_annotations(self, annotations: List[Annotation]):
        self._annotations = annotations
        self._rebuild_base_and_display()

    def clear(self):
        self.load_pdf(None, [])

    def set_active_tool(self, tool: Optional[str]):
        if tool != self._active_tool:
            self._line_start = None
            self._preview_pos = None
            self._close_stamp_popup()
            data_store.dbg(f"Tool changed: {self._active_tool!r} → {tool!r}")
        self._active_tool = tool
        for t, btn in self._tool_buttons.items():
            btn.setChecked(t == tool)

    def deselect_tool(self):
        self.set_active_tool(TOOL_NONE)

    def get_annotations(self) -> List[Annotation]:
        return self._annotations

    def set_preset_annotations(self, presets: List[str]):
        """Update the list of preset texts available to the Stamp tool."""
        self._preset_annotations = list(presets)

    def prev_page(self):
        """Navigate to the previous page (public, also used by shortcuts)."""
        self._prev_page()

    def next_page(self):
        """Navigate to the next page (public, also used by shortcuts)."""
        self._next_page()

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _page_size(self) -> Tuple[int, int]:
        """Return *(width, height)* of the current page pixmap in logical pixels."""
        pm = self._page_label.pixmap()
        return _pm_logical_size(pm)

    def _show_placeholder(self):
        self._raw_pixmap = None
        self._base_pixmap = None
        self._page_label.setPixmap(QPixmap())
        self._page_label.setText("No PDF loaded.\nSelect a student from the list.")
        self._page_label.resize(400, 300)
        self._page_counter.setText("Page — / —")
        self._prev_btn.setEnabled(False)
        self._next_btn.setEnabled(False)

    def _render_page(self):
        """Full re-render: rasterise via fitz (slow), then bake annotations."""
        if not self._doc:
            self._show_placeholder()
            return
        n = self._doc.page_count
        self._page_counter.setText(f"Page {self._current_page + 1} / {n}")
        self._prev_btn.setEnabled(self._current_page > 0)
        self._next_btn.setEnabled(self._current_page < n - 1)

        page = self._doc[self._current_page]
        # Scale by the device pixel ratio so Retina/HiDPI screens get a
        # sharp raster instead of an upscaled blurry image.
        dpr = self.devicePixelRatio()
        data_store.dbg(f"Rendering page {self._current_page + 1}/{n} at zoom {self._zoom:.2f} "
                       f"dpr {dpr:.1f} "
                       f"(page size: {page.rect.width:.0f}×{page.rect.height:.0f} pt)")
        # page.rect is already rotation-aware in PyMuPDF, so landscape A3 pages
        # get their correct (wide) dimensions here automatically.
        mat = fitz.Matrix(self._zoom * dpr, self._zoom * dpr)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height,
                     pix.stride, QImage.Format.Format_RGB888)
        raw = QPixmap.fromImage(img)
        raw.setDevicePixelRatio(dpr)
        self._raw_pixmap = raw
        self._zoom_label.setText(f"{int(self._zoom * 100)}%")
        self._rebuild_base_and_display()

    def _rebuild_base_and_display(self):
        """Redraw all annotations onto the cached raw page, refresh display."""
        if self._raw_pixmap is None:
            return
        self._base_pixmap = annotation_overlay.draw_annotations(
            self._raw_pixmap, self._annotations, self._current_page
        )
        self._update_display()

    def _update_display(self):
        """Compose base + optional preview, push to screen."""
        if self._base_pixmap is None:
            return
        if (self._active_tool in (TOOL_LINE, TOOL_ARROW, TOOL_CIRCLE, TOOL_RECTCROSS)
                and self._line_start is not None
                and self._preview_pos is not None):
            display = self._base_pixmap.copy()
            annotation_overlay.draw_preview(
                display, self._active_tool,
                self._line_start, self._preview_pos,
            )
        else:
            display = self._base_pixmap
        self._page_label.setPixmap(display)
        dpr = display.devicePixelRatio()
        self._page_label.resize(
            int(display.width() / dpr), int(display.height() / dpr)
        )

    # ── Mouse handlers ────────────────────────────────────────────────────────

    def _on_page_pressed(self, fx: float, fy: float):
        self._drag_moved = False
        # Cmd/Ctrl + left-click → start panning
        if QApplication.queryKeyboardModifiers() & _PAN_MOD:
            vp = self._scroll.viewport()
            cur = vp.mapFromGlobal(QCursor.pos())
            self._pan_origin = (cur.x(), cur.y())
            self._pan_hval = self._scroll.horizontalScrollBar().value()
            self._pan_vval = self._scroll.verticalScrollBar().value()
            self._page_label.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self._active_tool in (TOOL_NONE, None):
            drag = self._find_drag_target(fx, fy)
            if drag is not None:
                self._drag = drag
                return
        self._handle_click(fx, fy)

    def _on_page_moved(self, fx: float, fy: float):
        # Active pan — use raw viewport pixel coordinates to avoid clamping jitter
        if self._pan_origin is not None:
            vp = self._scroll.viewport()
            cur = vp.mapFromGlobal(QCursor.pos())
            dx = cur.x() - self._pan_origin[0]
            dy = cur.y() - self._pan_origin[1]
            self._scroll.horizontalScrollBar().setValue(int(self._pan_hval - dx))
            self._scroll.verticalScrollBar().setValue(int(self._pan_vval - dy))
            return
        # Hover cursor hints
        if QApplication.queryKeyboardModifiers() & _PAN_MOD:
            self._page_label.setCursor(Qt.CursorShape.OpenHandCursor)
        elif self._drag is None and self._active_tool in (TOOL_NONE, None):
            # Show grab cursor when hovering over a draggable annotation
            drag = self._find_drag_target(fx, fy)
            if drag is not None:
                if drag.kind == "text-resize":
                    self._page_label.setCursor(Qt.CursorShape.SizeHorCursor)
                elif drag.kind == "circle-edge":
                    self._page_label.setCursor(Qt.CursorShape.SizeVerCursor)
                elif drag.kind in ("rectcross-tl", "rectcross-tr",
                                    "rectcross-bl", "rectcross-br"):
                    self._page_label.setCursor(Qt.CursorShape.SizeAllCursor)
                else:
                    self._page_label.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self._page_label.unsetCursor()
        else:
            self._page_label.unsetCursor()
        if self._drag is not None:
            self._drag_moved = True
            self._apply_drag(fx, fy)
            return
        if (self._active_tool in (TOOL_LINE, TOOL_ARROW, TOOL_CIRCLE, TOOL_RECTCROSS)
                and self._line_start is not None):
            self._preview_pos = (fx, fy)
            self._update_display()

    def _on_page_released(self, fx: float, fy: float):
        # End pan
        if self._pan_origin is not None:
            self._pan_origin = None
            self._page_label.unsetCursor()
            return
        if self._drag is not None:
            self._apply_drag(fx, fy)
            self._drag = None
            if self._drag_moved:
                self._rebuild_base_and_display()
                self.annotations_changed.emit()

    # ── Annotation placement ──────────────────────────────────────────────────

    def _handle_click(self, fx: float, fy: float):
        if self._active_tool in (TOOL_NONE, None):
            return

        if self._active_tool == TOOL_ERASER:
            w, h = self._page_size()
            idx = annotation_overlay.find_annotation_at(
                self._annotations, self._current_page, fx, fy, w, h
            )
            if idx >= 0:
                self._annotations.pop(idx)
                self._rebuild_base_and_display()
                self.annotations_changed.emit()

        elif self._active_tool == TOOL_TEXT:
            w, h = self._page_size()
            idx = self._find_text_at(fx, fy, w, h)
            if idx >= 0:
                self._start_text_edit(
                    self._annotations[idx].x,
                    self._annotations[idx].y,
                    edit_idx=idx,
                )
            else:
                self._start_text_edit(fx, fy)

        elif self._active_tool in (TOOL_LINE, TOOL_ARROW, TOOL_CIRCLE, TOOL_RECTCROSS):
            if self._line_start is None:
                self._line_start = (fx, fy)
                self._preview_pos = (fx, fy)
            else:
                x1, y1 = self._line_start
                self._line_start = None
                self._preview_pos = None
                if self._active_tool == TOOL_CIRCLE:
                    # Normalise the edge point so the resize handle is always
                    # at the visual bottom of the circle.
                    pw, ph = self._page_size()
                    radius_px = math.hypot((fx - x1) * pw, (fy - y1) * ph)
                    x2, y2 = x1, y1 + radius_px / ph
                else:
                    x2, y2 = fx, fy
                self._annotations.append(Annotation(
                    page=self._current_page,
                    type=self._active_tool,
                    x=x1, y=y1, x2=x2, y2=y2,
                ))
                self._rebuild_base_and_display()
                self.annotations_changed.emit()
                self.deselect_tool()

        elif self._active_tool == TOOL_STAMP:
            self._show_stamp_popup(fx, fy)

        else:  # checkmark, cross, or tilde
            self._annotations.append(Annotation(
                page=self._current_page,
                type=self._active_tool,
                x=fx, y=fy,
            ))
            self._rebuild_base_and_display()
            self.annotations_changed.emit()
            self.deselect_tool()

    # ── Double-click: edit existing text annotation (any tool mode) ───────────

    def _on_page_double_clicked(self, fx: float, fy: float):
        """Double-clicking a text annotation opens it for editing."""
        # Only handle when no shape-drawing tool is active (text tool already
        # handles editing on single-click).
        if self._active_tool not in (TOOL_NONE, None):
            return
        pm = self._page_label.pixmap()
        if not pm or pm.isNull():
            return
        w, h = _pm_logical_size(pm)
        idx = self._find_text_at(fx, fy, w, h)
        if idx >= 0:
            ann = self._annotations[idx]
            self._start_text_edit(ann.x, ann.y, edit_idx=idx)

    # ── Drag helpers ──────────────────────────────────────────────────────────

    def _apply_drag(self, fx: float, fy: float):
        d = self._drag
        if d is None:
            return
        ann = self._annotations[d.index]
        dx, dy = fx - d.start_fx, fy - d.start_fy

        def cl(v):
            return max(0.0, min(1.0, v))

        if d.kind == "point":
            ann.x, ann.y = cl(d.orig_x + dx), cl(d.orig_y + dy)
        elif d.kind == "line-start":
            # Use offset from the original start point so there is no jump
            ann.x, ann.y = cl(d.orig_x + dx), cl(d.orig_y + dy)
        elif d.kind == "line-end":
            # Use offset from the original end point so there is no jump
            ann.x2, ann.y2 = cl(d.orig_x2 + dx), cl(d.orig_y2 + dy)
        elif d.kind == "line-move":
            ann.x,  ann.y  = cl(d.orig_x  + dx), cl(d.orig_y  + dy)
            ann.x2, ann.y2 = cl(d.orig_x2 + dx), cl(d.orig_y2 + dy)
        elif d.kind == "circle-edge":
            # Keep the resize handle always at the visual bottom.
            # New radius = euclidean distance from center to current mouse position.
            pw, ph = self._page_size()
            radius_px = math.hypot((fx - d.orig_x) * pw, (fy - d.orig_y) * ph)
            ann.x2 = d.orig_x
            ann.y2 = cl(d.orig_y + radius_px / ph)
        elif d.kind == "circle-move":
            ann.x,  ann.y  = cl(d.orig_x  + dx), cl(d.orig_y  + dy)
            ann.x2, ann.y2 = cl(d.orig_x2 + dx), cl(d.orig_y2 + dy)
        elif d.kind == "text-resize":
            ann.width = max(0.02, min(1.0, d.orig_width + dx))
        elif d.kind == "rectcross-move":
            ann.x,  ann.y  = cl(d.orig_x  + dx), cl(d.orig_y  + dy)
            ann.x2, ann.y2 = cl(d.orig_x2 + dx), cl(d.orig_y2 + dy)
        elif d.kind == "rectcross-tl":
            ann.x = cl(d.orig_x + dx)
            ann.y = cl(d.orig_y + dy)
        elif d.kind == "rectcross-tr":
            ann.x2 = cl(d.orig_x2 + dx)
            ann.y  = cl(d.orig_y  + dy)
        elif d.kind == "rectcross-bl":
            ann.x  = cl(d.orig_x  + dx)
            ann.y2 = cl(d.orig_y2 + dy)
        elif d.kind == "rectcross-br":
            ann.x2 = cl(d.orig_x2 + dx)
            ann.y2 = cl(d.orig_y2 + dy)

        self._rebuild_base_and_display()

    def _find_drag_target(self, fx: float, fy: float) -> Optional[_DragState]:
        pm = self._page_label.pixmap()
        if not pm or pm.isNull():
            return None
        w, h = _pm_logical_size(pm)
        tol = _DRAG_TOL
        mx, my = fx * w, fy * h

        # Iterate in reverse so the topmost (last-drawn) annotation wins
        for i in range(len(self._annotations) - 1, -1, -1):
            ann = self._annotations[i]
            if ann.page != self._current_page:
                continue

            if ann.type in ("line", "arrow") and ann.x2 is not None:
                x1, y1 = ann.x * w, ann.y * h
                x2, y2 = ann.x2 * w, ann.y2 * h
                if math.hypot(mx - x1, my - y1) <= tol:
                    return _DragState("line-start", i, fx, fy, ann.x, ann.y, ann.x2, ann.y2)
                if math.hypot(mx - x2, my - y2) <= tol:
                    return _DragState("line-end", i, fx, fy, ann.x, ann.y, ann.x2, ann.y2)
                if annotation_overlay._pt_seg_dist(mx, my, x1, y1, x2, y2) <= tol:
                    return _DragState("line-move", i, fx, fy, ann.x, ann.y, ann.x2, ann.y2)

            elif ann.type == "circle" and ann.x2 is not None:
                cx, cy = ann.x * w, ann.y * h
                radius = math.hypot((ann.x2 - ann.x) * w, (ann.y2 - ann.y) * h)
                # Resize handle is always drawn at the visual bottom of the circle
                bx, by = cx, cy + radius
                if math.hypot(mx - bx, my - by) <= tol:
                    return _DragState("circle-edge", i, fx, fy, ann.x, ann.y, ann.x2, ann.y2)
                # Move: grab near the circumference (but not the handle area)
                if abs(math.hypot(mx - cx, my - cy) - radius) <= tol:
                    return _DragState("circle-move", i, fx, fy, ann.x, ann.y, ann.x2, ann.y2)

            elif ann.type == "rectcross" and ann.x2 is not None:
                # 4 corners of the rectangle
                corners = [
                    (ann.x * w, ann.y * h),
                    (ann.x2 * w, ann.y * h),
                    (ann.x * w, ann.y2 * h),
                    (ann.x2 * w, ann.y2 * h),
                ]
                corner_kinds = [
                    "rectcross-tl", "rectcross-tr",
                    "rectcross-bl", "rectcross-br",
                ]
                for (ccx, ccy), kind in zip(corners, corner_kinds):
                    if math.hypot(mx - ccx, my - ccy) <= tol:
                        return _DragState(kind, i, fx, fy, ann.x, ann.y, ann.x2, ann.y2)
                # Move: grab on either diagonal line
                x1, y1 = ann.x * w, ann.y * h
                x2, y2 = ann.x2 * w, ann.y2 * h
                d1 = annotation_overlay._pt_seg_dist(mx, my, x1, y1, x2, y2)
                d2 = annotation_overlay._pt_seg_dist(mx, my, x2, y1, x1, y2)
                if min(d1, d2) <= tol:
                    return _DragState("rectcross-move", i, fx, fy, ann.x, ann.y, ann.x2, ann.y2)

            elif ann.type == "text":
                rect = annotation_overlay.get_text_box_rect(ann, w, h)
                if rect is None:
                    continue
                hs = max(4, round(annotation_overlay._RESIZE_HANDLE
                                  * h / annotation_overlay.BASE_PAGE_HEIGHT))
                # Bottom-right resize handle zone (generous hit area)
                if (rect.right() - hs <= mx <= rect.right() + 4
                        and rect.bottom() - hs <= my <= rect.bottom() + 4):
                    ow = ann.width if ann.width is not None else rect.width() / w
                    return _DragState("text-resize", i, fx, fy, ann.x, ann.y,
                                      orig_width=ow)
                if rect.contains(int(mx), int(my)):
                    return _DragState("point", i, fx, fy, ann.x, ann.y)

            else:  # checkmark, cross
                if math.hypot((ann.x - fx) * w, (ann.y - fy) * h) <= tol:
                    return _DragState("point", i, fx, fy, ann.x, ann.y)

        return None

    def _find_text_at(self, fx: float, fy: float, w: int, h: int) -> int:
        for i, ann in enumerate(self._annotations):
            if ann.page != self._current_page or ann.type != "text":
                continue
            rect = annotation_overlay.get_text_box_rect(ann, w, h)
            if rect and rect.contains(int(fx * w), int(fy * h)):
                return i
        return -1

    # ── Inline text editor ────────────────────────────────────────────────────

    def _start_text_edit(self, fx: float, fy: float, edit_idx: int = -1):
        self._cancel_inline_editor()
        pm = self._page_label.pixmap()
        if not pm or pm.isNull():
            return

        # Scale font to match the rendered annotation size
        lw, lh = _pm_logical_size(pm)
        s = lh / annotation_overlay.BASE_PAGE_HEIGHT
        font_pt = max(4, round(annotation_overlay._TEXT_FONT_PT * s))

        cx = int(fx * lw)
        cy = int(fy * lh)
        vp = self._scroll.viewport()
        pos = self._page_label.mapTo(vp, QPoint(cx, cy))

        editor = InlineTextEdit(font_pt, vp)
        editor.setMinimumWidth(_INLINE_EDITOR_MIN_W)
        editor.move(pos)
        if edit_idx >= 0:
            ann = self._annotations[edit_idx]
            rect = annotation_overlay.get_text_box_rect(ann, lw, lh)
            # Set width first so word-wrap height calculation is correct when
            # setPlainText triggers _adjust_height.
            init_w = max(rect.width(), _INLINE_EDITOR_MIN_W) if rect else _INLINE_EDITOR_WIDTH
            editor.resize(init_w, editor.height())
            editor.setPlainText(self._annotations[edit_idx].text or "")
            editor.selectAll()
        else:
            editor.resize(_INLINE_EDITOR_WIDTH, editor.height())
        editor.show()
        editor.setFocus()
        # Defer height adjustment so the widget geometry is finalised
        QTimer.singleShot(0, editor._adjust_height)
        self._inline_editor = editor

        def _commit(text: str):
            self._inline_editor = None
            editor.deleteLater()
            if text.strip():
                # Only record width as a fraction of the page; height is always
                # computed automatically from the text content.
                width_frac = editor.width() / lw if lw > 0 else None
                if edit_idx >= 0:
                    self._annotations[edit_idx].text = text.strip()
                    self._annotations[edit_idx].width = width_frac
                else:
                    self._annotations.append(Annotation(
                        page=self._current_page, type="text",
                        x=fx, y=fy, text=text.strip(),
                        width=width_frac,
                    ))
                self._rebuild_base_and_display()
                self.annotations_changed.emit()
            self.deselect_tool()

        def _cancel():
            self._inline_editor = None
            editor.deleteLater()

        editor.committed.connect(_commit)
        editor.cancelled.connect(_cancel)

    def _cancel_inline_editor(self):
        if self._inline_editor is not None:
            self._inline_editor.deleteLater()
            self._inline_editor = None

    # ── Stamp popup (preset text annotation picker) ──────────────────────────

    def _show_stamp_popup(self, fx: float, fy: float):
        self._close_stamp_popup()
        if not self._preset_annotations:
            return
        pm = self._page_label.pixmap()
        if not pm or pm.isNull():
            return

        vp = self._scroll.viewport()
        lw, lh = _pm_logical_size(pm)
        cx = int(fx * lw)
        cy = int(fy * lh)
        pos = self._page_label.mapTo(vp, QPoint(cx, cy))

        popup = QWidget(vp)
        popup.setStyleSheet(
            "QWidget { background: #fff; border: 1px solid #888; }"
        )
        playout = QVBoxLayout(popup)
        playout.setContentsMargins(4, 4, 4, 4)
        playout.setSpacing(2)

        filter_edit = QLineEdit()
        filter_edit.setPlaceholderText("Filter presets…")
        filter_edit.setStyleSheet("QLineEdit { border: 1px solid #ccc; }")
        playout.addWidget(filter_edit)

        preset_list = QListWidget()
        preset_list.setStyleSheet(
            "QListWidget { border: none; }"
            "QListWidget::item { padding: 3px; }"
            "QListWidget::item:hover { background: #e0e8f0; }"
        )
        for text in self._preset_annotations:
            preset_list.addItem(QListWidgetItem(text))
        playout.addWidget(preset_list)

        def _first_visible_item():
            for i in range(preset_list.count()):
                item = preset_list.item(i)
                if not item.isHidden():
                    return item
            return None

        def _filter_presets(query: str):
            q = query.strip().lower()
            for i in range(preset_list.count()):
                item = preset_list.item(i)
                item.setHidden(q != "" and q not in item.text().lower())
            # Keep the first visible item selected so Enter always picks something
            first = _first_visible_item()
            if first:
                preset_list.setCurrentItem(first)
            else:
                preset_list.clearSelection()

        filter_edit.textChanged.connect(_filter_presets)

        def _on_pick(item: QListWidgetItem):
            if item is None or item.isHidden():
                return
            text = item.text()
            self._close_stamp_popup()
            self._annotations.append(Annotation(
                page=self._current_page, type="text",
                x=fx, y=fy, text=text,
            ))
            self._rebuild_base_and_display()
            self.annotations_changed.emit()
            self.deselect_tool()

        preset_list.itemClicked.connect(_on_pick)
        preset_list.itemActivated.connect(_on_pick)

        _filter_orig_kp = filter_edit.keyPressEvent
        _list_orig_kp   = preset_list.keyPressEvent

        def _filter_key_press(event):
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # Pick the first visible / currently selected item
                item = preset_list.currentItem() or _first_visible_item()
                if item and not item.isHidden():
                    _on_pick(item)
                return
            if key == Qt.Key.Key_Down:
                # Move selection focus to the list
                first = _first_visible_item()
                if first:
                    preset_list.setCurrentItem(first)
                    preset_list.setFocus()
                return
            if key == Qt.Key.Key_Escape:
                self._close_stamp_popup()
                return
            _filter_orig_kp(event)

        filter_edit.keyPressEvent = _filter_key_press

        def _list_key_press(event):
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = preset_list.currentItem()
                if item and not item.isHidden():
                    _on_pick(item)
                return
            if key == Qt.Key.Key_Up:
                # Return focus to filter when Up is pressed on the first visible item
                if preset_list.currentItem() is _first_visible_item():
                    filter_edit.setFocus()
                    return
            if key == Qt.Key.Key_Escape:
                self._close_stamp_popup()
                return
            _list_orig_kp(event)

        preset_list.keyPressEvent = _list_key_press

        # Select the first item by default so Enter works immediately
        first = _first_visible_item()
        if first:
            preset_list.setCurrentItem(first)

        edit_btn = QPushButton("Edit Presets…")
        edit_btn.setStyleSheet("QPushButton { border: 1px solid #ccc; padding: 3px; }")
        def _on_edit_presets():
            self._close_stamp_popup()
            self.deselect_tool()
            self.open_settings_presets_requested.emit()
        edit_btn.clicked.connect(_on_edit_presets)
        playout.addWidget(edit_btn)

        popup.adjustSize()
        # Ensure popup fits within viewport
        pw, ph = popup.width(), popup.height()
        vw, vh = vp.width(), vp.height()
        px = min(pos.x(), max(0, vw - pw))
        py = min(pos.y(), max(0, vh - ph))
        popup.move(px, py)
        popup.show()
        popup.raise_()
        filter_edit.setFocus()
        self._stamp_popup = popup

    def _close_stamp_popup(self):
        if self._stamp_popup is not None:
            self._stamp_popup.deleteLater()
            self._stamp_popup = None

    # ── Navigation / zoom ─────────────────────────────────────────────────────

    def _prev_page(self):
        if self._doc and self._current_page > 0:
            self._current_page -= 1
            data_store.dbg(f"Navigating to previous page: {self._current_page + 1}")
            self._line_start = None
            self._preview_pos = None
            self._drag = None
            self._cancel_inline_editor()
            self._render_page()

    def _next_page(self):
        if self._doc and self._current_page < self._doc.page_count - 1:
            self._current_page += 1
            data_store.dbg(f"Navigating to next page: {self._current_page + 1}")
            self._line_start = None
            self._preview_pos = None
            self._drag = None
            self._cancel_inline_editor()
            self._render_page()

    def _on_tool_clicked(self, tool: str, checked: bool):
        self.set_active_tool(tool if checked else TOOL_NONE)

    # ── Gesture / wheel zoom ──────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        """Intercept scroll-viewport events for zoom gestures."""
        if obj is self._scroll.viewport():
            t = event.type()
            # Ctrl + scroll wheel → zoom (works on all platforms)
            if t == QEvent.Type.Wheel:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    delta = event.angleDelta().y()
                    if delta:
                        self._apply_zoom_factor(1.0 + delta / _WHEEL_ZOOM_DIVISOR)
                    return True
            # Native pinch gesture → zoom (macOS trackpad)
            elif t == QEvent.Type.NativeGesture:
                if (event.gestureType()
                        == Qt.NativeGestureType.ZoomNativeGesture):
                    self._apply_zoom_factor(1.0 + event.value())
                    return True
        return super().eventFilter(obj, event)

    def _apply_zoom_factor(self, factor: float):
        """Multiply current zoom by *factor*, clamped to [0.5, 3.0]."""
        new_zoom = max(0.5, min(3.0, self._zoom * factor))
        if abs(new_zoom - self._zoom) > 0.005:
            self._zoom = new_zoom
            self._render_page()

    def _zoom_in(self):
        if self._zoom < 3.0:
            self._zoom = min(3.0, self._zoom + 0.2)
            self._render_page()

    def _zoom_out(self):
        if self._zoom > 0.5:
            self._zoom = max(0.5, self._zoom - 0.2)
            self._render_page()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self._line_start is not None:
                self._line_start = None
                self._preview_pos = None
                self._update_display()
            else:
                self.deselect_tool()
        super().keyPressEvent(event)
