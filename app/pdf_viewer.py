"""Center panel: PDF viewer with annotation support."""
import os
from typing import List, Optional, Tuple

import fitz  # pymupdf
from PySide6.QtCore import QObject, QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import annotation_overlay
from models import Annotation

TOOL_NONE = None
TOOL_CHECKMARK = "checkmark"
TOOL_CROSS = "cross"
TOOL_TEXT = "text"
TOOL_LINE = "line"
TOOL_ARROW = "arrow"
TOOL_CIRCLE = "circle"
TOOL_ERASER = "eraser"

# Keyboard shortcut → tool mapping (matches the old web app)
_KEY_TOOL_MAP = {
    Qt.Key.Key_V: TOOL_CHECKMARK,
    Qt.Key.Key_X: TOOL_CROSS,
    Qt.Key.Key_T: TOOL_TEXT,
    Qt.Key.Key_L: TOOL_LINE,
    Qt.Key.Key_A: TOOL_ARROW,
    Qt.Key.Key_O: TOOL_CIRCLE,
    Qt.Key.Key_E: TOOL_ERASER,
}


class InlineTextEdit(QLineEdit):
    """Floating one-line editor used for in-place text annotations."""

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
    """Application-level event filter that routes tool keyboard shortcuts."""

    def __init__(self, viewer: "PDFViewerPanel", parent=None):
        super().__init__(parent)
        self._viewer = viewer

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            focused = QApplication.focusWidget()
            # Don't steal keystrokes from text-input widgets
            if isinstance(focused, QLineEdit):
                return False
            key = event.key()
            if key in _KEY_TOOL_MAP:
                tool = _KEY_TOOL_MAP[key]
                # Toggle: pressing the active tool's key deselects it
                new_tool = None if self._viewer._active_tool == tool else tool
                self._viewer.set_active_tool(new_tool)
                return True
            if key == Qt.Key.Key_Escape:
                if self._viewer._line_start is not None:
                    self._viewer._line_start = None
                    self._viewer._render_page()
                else:
                    self._viewer.deselect_tool()
                return True
        return False


class ClickableLabel(QLabel):
    """A QLabel that emits a click signal with fractional coordinates."""
    clicked = Signal(float, float)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            w = self.width()
            h = self.height()
            if w > 0 and h > 0:
                fx = event.position().x() / w
                fy = event.position().y() / h
                self.clicked.emit(fx, fy)
        super().mousePressEvent(event)


class PDFViewerPanel(QWidget):
    annotations_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pdf_path: Optional[str] = None
        self._doc: Optional[fitz.Document] = None
        self._current_page: int = 0
        self._zoom: float = 1.2
        self._annotations: List[Annotation] = []
        self._active_tool: Optional[str] = TOOL_NONE
        self._line_start: Optional[Tuple[float, float]] = None  # for line/arrow/circle
        self._inline_editor: Optional[InlineTextEdit] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QWidget()
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(4, 4, 4, 4)

        self._tool_buttons = {}
        tools = [
            (TOOL_CHECKMARK, "✓", "Checkmark (V)"),
            (TOOL_CROSS, "✗", "Cross (X)"),
            (TOOL_TEXT,  "T", "Text (T)"),
            (TOOL_LINE,  "╱", "Line (L)"),
            (TOOL_ARROW, "→", "Arrow (A)"),
            (TOOL_CIRCLE,"○", "Circle (O)"),
            (TOOL_ERASER,"✎", "Eraser (E)"),
        ]
        for tool_id, label, tooltip in tools:
            btn = QPushButton(label)
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.setFixedWidth(36)
            btn.clicked.connect(lambda checked, t=tool_id: self._on_tool_clicked(t, checked))
            tb_layout.addWidget(btn)
            self._tool_buttons[tool_id] = btn

        tb_layout.addStretch()

        # Zoom buttons
        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setFixedWidth(32)
        zoom_out_btn.setToolTip("Zoom out")
        zoom_out_btn.clicked.connect(self._zoom_out)
        tb_layout.addWidget(zoom_out_btn)

        self._zoom_label = QLabel("120%")
        self._zoom_label.setFixedWidth(50)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tb_layout.addWidget(self._zoom_label)

        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedWidth(32)
        zoom_in_btn.setToolTip("Zoom in")
        zoom_in_btn.clicked.connect(self._zoom_in)
        tb_layout.addWidget(zoom_in_btn)

        layout.addWidget(toolbar)

        # Scroll area for the page image
        self._scroll = QScrollArea()
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidgetResizable(False)

        self._page_label = ClickableLabel()
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.clicked.connect(self._on_page_clicked)
        self._scroll.setWidget(self._page_label)
        layout.addWidget(self._scroll, stretch=1)

        # Page navigation bar
        nav = QWidget()
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(4, 4, 4, 4)

        self._prev_btn = QPushButton("◀ Prev")
        self._prev_btn.clicked.connect(self._prev_page)
        nav_layout.addWidget(self._prev_btn)

        self._page_counter = QLabel("Page 1 / 1")
        self._page_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(self._page_counter, stretch=1)

        self._next_btn = QPushButton("Next ▶")
        self._next_btn.clicked.connect(self._next_page)
        nav_layout.addWidget(self._next_btn)

        layout.addWidget(nav)

        self._show_placeholder()

        # Install application-level keyboard shortcut filter
        self._shortcut_filter = _ToolShortcutFilter(self)
        QApplication.instance().installEventFilter(self._shortcut_filter)

    # ── Public API ────────────────────────────────────────────────────────────

    def load_pdf(self, pdf_path: Optional[str], annotations: List[Annotation]):
        """Load a PDF file and its annotations. Pass None to show placeholder."""
        if self._doc:
            self._doc.close()
            self._doc = None

        self._annotations = annotations
        self._current_page = 0
        self._line_start = None
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
        self._render_page()

    def clear(self):
        self.load_pdf(None, [])

    def set_active_tool(self, tool: Optional[str]):
        # Cancel in-progress shape drawing when tool changes
        if tool != self._active_tool:
            self._line_start = None
        self._active_tool = tool
        for t, btn in self._tool_buttons.items():
            btn.setChecked(t == tool)

    def deselect_tool(self):
        self.set_active_tool(TOOL_NONE)

    def get_annotations(self) -> List[Annotation]:
        return self._annotations

    # ── Internal ──────────────────────────────────────────────────────────────

    def _show_placeholder(self):
        self._page_label.setPixmap(QPixmap())
        self._page_label.setText("No PDF loaded.\nSelect a student from the list.")
        self._page_label.resize(400, 300)
        self._page_counter.setText("Page — / —")
        self._prev_btn.setEnabled(False)
        self._next_btn.setEnabled(False)

    def _render_page(self):
        if not self._doc:
            self._show_placeholder()
            return

        page_count = self._doc.page_count
        self._page_counter.setText(f"Page {self._current_page + 1} / {page_count}")
        self._prev_btn.setEnabled(self._current_page > 0)
        self._next_btn.setEnabled(self._current_page < page_count - 1)

        page = self._doc[self._current_page]
        mat = fitz.Matrix(self._zoom, self._zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img = QImage(
            pix.samples, pix.width, pix.height,
            pix.stride, QImage.Format.Format_RGB888
        )
        pixmap = QPixmap.fromImage(img)

        # Draw annotations on top
        pixmap = annotation_overlay.draw_annotations(
            pixmap, self._annotations, self._current_page
        )

        self._page_label.setPixmap(pixmap)
        self._page_label.resize(pixmap.size())
        self._zoom_label.setText(f"{int(self._zoom * 100)}%")

    def _on_tool_clicked(self, tool: str, checked: bool):
        if checked:
            self.set_active_tool(tool)
        else:
            self.set_active_tool(TOOL_NONE)

    def _on_page_clicked(self, fx: float, fy: float):
        if self._active_tool is None or self._active_tool == TOOL_NONE:
            return

        if self._active_tool == TOOL_ERASER:
            pixmap = self._page_label.pixmap()
            w = pixmap.width() if pixmap else 1
            h = pixmap.height() if pixmap else 1
            idx = annotation_overlay.find_annotation_at(
                self._annotations, self._current_page, fx, fy, w, h
            )
            if idx >= 0:
                self._annotations.pop(idx)
                self._render_page()
                self.annotations_changed.emit()

        elif self._active_tool == TOOL_TEXT:
            self._start_inline_text_edit(fx, fy)

        elif self._active_tool in (TOOL_LINE, TOOL_ARROW, TOOL_CIRCLE):
            if self._line_start is None:
                # First click: record start point
                self._line_start = (fx, fy)
            else:
                # Second click: complete the shape
                x1, y1 = self._line_start
                self._line_start = None
                ann = Annotation(
                    page=self._current_page,
                    type=self._active_tool,
                    x=x1, y=y1,
                    x2=fx, y2=fy,
                )
                self._annotations.append(ann)
                self._render_page()
                self.annotations_changed.emit()

        else:
            ann = Annotation(
                page=self._current_page,
                type=self._active_tool,
                x=fx, y=fy,
            )
            self._annotations.append(ann)
            self._render_page()
            self.annotations_changed.emit()

    def _start_inline_text_edit(self, fx: float, fy: float):
        """Show a floating text input directly at the clicked position."""
        self._cancel_inline_editor()
        pixmap = self._page_label.pixmap()
        if not pixmap or pixmap.isNull():
            return

        cx = int(fx * pixmap.width())
        cy = int(fy * pixmap.height())

        # Map label-local point to the scroll viewport's coordinate system
        vp = self._scroll.viewport()
        pos_in_vp = self._page_label.mapTo(vp, QPoint(cx, cy))

        editor = InlineTextEdit(vp)
        editor.setMinimumWidth(80)
        editor.resize(140, 22)
        editor.move(pos_in_vp)
        editor.show()
        editor.setFocus()
        self._inline_editor = editor

        def _commit(text: str):
            self._inline_editor = None
            editor.deleteLater()
            if text.strip():
                ann = Annotation(
                    page=self._current_page,
                    type="text",
                    x=fx, y=fy,
                    text=text.strip(),
                )
                self._annotations.append(ann)
                self._render_page()
                self.annotations_changed.emit()

        def _cancel():
            self._inline_editor = None
            editor.deleteLater()

        editor.committed.connect(_commit)
        editor.cancelled.connect(_cancel)

    def _cancel_inline_editor(self):
        if self._inline_editor is not None:
            self._inline_editor.deleteLater()
            self._inline_editor = None

    def _prev_page(self):
        if self._doc and self._current_page > 0:
            self._current_page -= 1
            self._line_start = None
            self._cancel_inline_editor()
            self._render_page()

    def _next_page(self):
        if self._doc and self._current_page < self._doc.page_count - 1:
            self._current_page += 1
            self._line_start = None
            self._cancel_inline_editor()
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
        # Handled by the application-level filter; keep Escape as fallback
        if event.key() == Qt.Key.Key_Escape:
            if self._line_start is not None:
                self._line_start = None
                self._render_page()
            else:
                self.deselect_tool()
        super().keyPressEvent(event)
