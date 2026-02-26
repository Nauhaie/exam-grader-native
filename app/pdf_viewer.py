"""Center panel: PDF viewer with annotation support."""
import os
from typing import List, Optional

import fitz  # pymupdf
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QToolBar, QVBoxLayout, QWidget,
)

import annotation_overlay
from models import Annotation

TOOL_NONE = None
TOOL_CHECKMARK = "checkmark"
TOOL_CROSS = "cross"
TOOL_TEXT = "text"
TOOL_ERASER = "eraser"


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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QWidget()
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(4, 4, 4, 4)

        self._tool_buttons = {}
        tools = [
            (TOOL_CHECKMARK, "✓", "Place checkmark (green)"),
            (TOOL_CROSS, "✗", "Place cross (red)"),
            (TOOL_TEXT, "T", "Place text label"),
            (TOOL_ERASER, "✎", "Erase annotation"),
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

    # ── Public API ────────────────────────────────────────────────────────────

    def load_pdf(self, pdf_path: Optional[str], annotations: List[Annotation]):
        """Load a PDF file and its annotations. Pass None to show placeholder."""
        if self._doc:
            self._doc.close()
            self._doc = None

        self._annotations = annotations
        self._current_page = 0

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
        self._active_tool = tool
        for t, btn in self._tool_buttons.items():
            btn.setChecked(t == tool)

    def deselect_tool(self):
        self.set_active_tool(TOOL_NONE)

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
            text, ok = QInputDialog.getText(self, "Text Annotation", "Enter text:")
            if ok and text.strip():
                ann = Annotation(
                    page=self._current_page,
                    type="text",
                    x=fx,
                    y=fy,
                    text=text.strip(),
                )
                self._annotations.append(ann)
                self._render_page()
                self.annotations_changed.emit()
        else:
            ann = Annotation(
                page=self._current_page,
                type=self._active_tool,
                x=fx,
                y=fy,
            )
            self._annotations.append(ann)
            self._render_page()
            self.annotations_changed.emit()

    def _prev_page(self):
        if self._doc and self._current_page > 0:
            self._current_page -= 1
            self._render_page()

    def _next_page(self):
        if self._doc and self._current_page < self._doc.page_count - 1:
            self._current_page += 1
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
            self.deselect_tool()
        super().keyPressEvent(event)
