"""Center panel: PDF viewer with annotation support."""
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import fitz  # pymupdf
from PySide6.QtCore import QObject, QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import annotation_overlay
from models import Annotation

TOOL_NONE     = None
TOOL_CHECKMARK = "checkmark"
TOOL_CROSS    = "cross"
TOOL_TEXT     = "text"
TOOL_LINE     = "line"
TOOL_ARROW    = "arrow"
TOOL_CIRCLE   = "circle"
TOOL_ERASER   = "eraser"

_KEY_TOOL_MAP = {
    Qt.Key.Key_V: TOOL_CHECKMARK,
    Qt.Key.Key_X: TOOL_CROSS,
    Qt.Key.Key_T: TOOL_TEXT,
    Qt.Key.Key_L: TOOL_LINE,
    Qt.Key.Key_A: TOOL_ARROW,
    Qt.Key.Key_O: TOOL_CIRCLE,
    Qt.Key.Key_E: TOOL_ERASER,
}

_DRAG_TOL = 20          # pixel hit-tolerance for drag handles
_WHEEL_ZOOM_DIVISOR = 800.0  # wheel-delta units that equal a 1× zoom step


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


class InlineTextEdit(QLineEdit):
    """Floating single-line editor for text annotations."""

    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._done = False
        self.setStyleSheet(
            "background: #ffff99; border: 1px solid #888;"
            " font-size: 9pt; font-weight: bold; padding: 1px;"
        )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if not self._done:
                self._done = True
                self.cancelled.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self._done:
                self._done = True
                self.committed.emit(self.text())
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        if not self._done:
            self._done = True
            text = self.text().strip()
            if text:
                self.committed.emit(text)
            else:
                self.cancelled.emit()
        super().focusOutEvent(event)


class _ToolShortcutFilter(QObject):
    """App-level event filter: tool keyboard shortcuts + 'P' jump."""

    def __init__(self, viewer: "PDFViewerPanel", parent=None):
        super().__init__(parent)
        self._viewer = viewer

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.KeyPress:
            return False
        if isinstance(QApplication.focusWidget(), QLineEdit):
            return False

        key = event.key()
        if key in _KEY_TOOL_MAP:
            tool = _KEY_TOOL_MAP[key]
            new = TOOL_NONE if self._viewer._active_tool == tool else tool
            self._viewer.set_active_tool(new)
            return True
        if key == Qt.Key.Key_P:
            self._viewer.jump_requested.emit()
            return True
        if key == Qt.Key.Key_Escape:
            if self._viewer._line_start is not None:
                self._viewer._line_start = None
                self._viewer._preview_pos = None
                self._viewer._update_display()
            else:
                self._viewer.deselect_tool()
            return True
        return False


class ClickableLabel(QLabel):
    """QLabel that emits fractional-coordinate mouse signals."""

    pressed  = Signal(float, float)
    moved    = Signal(float, float)
    released = Signal(float, float)

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


class PDFViewerPanel(QWidget):
    annotations_changed = Signal()
    jump_requested = Signal()   # emitted when user presses 'P'

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
        if pdf_path and os.path.isfile(pdf_path):
            self._pdf_path = pdf_path
            self._doc = fitz.open(pdf_path)
            self._render_page()
        else:
            self._pdf_path = None
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
        self._active_tool = tool
        for t, btn in self._tool_buttons.items():
            btn.setChecked(t == tool)

    def deselect_tool(self):
        self.set_active_tool(TOOL_NONE)

    def get_annotations(self) -> List[Annotation]:
        return self._annotations

    # ── Rendering ─────────────────────────────────────────────────────────────

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
        # page.rect is already rotation-aware in PyMuPDF, so landscape A3 pages
        # get their correct (wide) dimensions here automatically.
        mat = fitz.Matrix(self._zoom, self._zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height,
                     pix.stride, QImage.Format.Format_RGB888)
        self._raw_pixmap = QPixmap.fromImage(img)
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
        if (self._active_tool in (TOOL_LINE, TOOL_ARROW, TOOL_CIRCLE)
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
        self._page_label.resize(display.size())

    # ── Mouse handlers ────────────────────────────────────────────────────────

    def _on_page_pressed(self, fx: float, fy: float):
        self._drag_moved = False
        if self._active_tool in (TOOL_NONE, None):
            drag = self._find_drag_target(fx, fy)
            if drag is not None:
                self._drag = drag
                return
        self._handle_click(fx, fy)

    def _on_page_moved(self, fx: float, fy: float):
        if self._drag is not None:
            self._drag_moved = True
            self._apply_drag(fx, fy)
            return
        if (self._active_tool in (TOOL_LINE, TOOL_ARROW, TOOL_CIRCLE)
                and self._line_start is not None):
            self._preview_pos = (fx, fy)
            self._update_display()

    def _on_page_released(self, fx: float, fy: float):
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
            pm = self._page_label.pixmap()
            w = pm.width() if pm else 1
            h = pm.height() if pm else 1
            idx = annotation_overlay.find_annotation_at(
                self._annotations, self._current_page, fx, fy, w, h
            )
            if idx >= 0:
                self._annotations.pop(idx)
                self._rebuild_base_and_display()
                self.annotations_changed.emit()

        elif self._active_tool == TOOL_TEXT:
            pm = self._page_label.pixmap()
            w = pm.width() if pm else 1
            h = pm.height() if pm else 1
            idx = self._find_text_at(fx, fy, w, h)
            if idx >= 0:
                self._start_text_edit(
                    self._annotations[idx].x,
                    self._annotations[idx].y,
                    edit_idx=idx,
                )
            else:
                self._start_text_edit(fx, fy)

        elif self._active_tool in (TOOL_LINE, TOOL_ARROW, TOOL_CIRCLE):
            if self._line_start is None:
                self._line_start = (fx, fy)
                self._preview_pos = (fx, fy)
            else:
                x1, y1 = self._line_start
                self._line_start = None
                self._preview_pos = None
                self._annotations.append(Annotation(
                    page=self._current_page,
                    type=self._active_tool,
                    x=x1, y=y1, x2=fx, y2=fy,
                ))
                self._rebuild_base_and_display()
                self.annotations_changed.emit()
                self.deselect_tool()

        else:  # checkmark or cross
            self._annotations.append(Annotation(
                page=self._current_page,
                type=self._active_tool,
                x=fx, y=fy,
            ))
            self._rebuild_base_and_display()
            self.annotations_changed.emit()
            self.deselect_tool()

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
            ann.x, ann.y = cl(fx), cl(fy)
        elif d.kind == "line-end":
            ann.x2, ann.y2 = cl(fx), cl(fy)
        elif d.kind == "line-move":
            ann.x,  ann.y  = cl(d.orig_x  + dx), cl(d.orig_y  + dy)
            ann.x2, ann.y2 = cl(d.orig_x2 + dx), cl(d.orig_y2 + dy)
        elif d.kind == "circle-edge":
            ann.x2, ann.y2 = cl(fx), cl(fy)
        elif d.kind == "circle-move":
            ann.x,  ann.y  = cl(d.orig_x  + dx), cl(d.orig_y  + dy)
            ann.x2, ann.y2 = cl(d.orig_x2 + dx), cl(d.orig_y2 + dy)
        elif d.kind == "text-resize":
            ann.width = max(0.02, min(1.0, d.orig_width + dx))

        self._rebuild_base_and_display()

    def _find_drag_target(self, fx: float, fy: float) -> Optional[_DragState]:
        pm = self._page_label.pixmap()
        if not pm or pm.isNull():
            return None
        w, h = pm.width(), pm.height()
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
                ex, ey = ann.x2 * w, ann.y2 * h
                if math.hypot(mx - ex, my - ey) <= tol:
                    return _DragState("circle-edge", i, fx, fy, ann.x, ann.y, ann.x2, ann.y2)
                if math.hypot(mx - cx, my - cy) <= radius + tol:
                    return _DragState("circle-move", i, fx, fy, ann.x, ann.y, ann.x2, ann.y2)

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
        cx = int(fx * pm.width())
        cy = int(fy * pm.height())
        vp = self._scroll.viewport()
        pos = self._page_label.mapTo(vp, QPoint(cx, cy))

        editor = InlineTextEdit(vp)
        editor.setMinimumWidth(80)
        editor.resize(140, 22)
        editor.move(pos)
        if edit_idx >= 0:
            editor.setText(self._annotations[edit_idx].text or "")
            editor.selectAll()
        editor.show()
        editor.setFocus()
        self._inline_editor = editor

        def _commit(text: str):
            self._inline_editor = None
            editor.deleteLater()
            if text.strip():
                if edit_idx >= 0:
                    self._annotations[edit_idx].text = text.strip()
                else:
                    self._annotations.append(Annotation(
                        page=self._current_page, type="text",
                        x=fx, y=fy, text=text.strip(),
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

    # ── Navigation / zoom ─────────────────────────────────────────────────────

    def _prev_page(self):
        if self._doc and self._current_page > 0:
            self._current_page -= 1
            self._line_start = None
            self._preview_pos = None
            self._drag = None
            self._cancel_inline_editor()
            self._render_page()

    def _next_page(self):
        if self._doc and self._current_page < self._doc.page_count - 1:
            self._current_page += 1
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
