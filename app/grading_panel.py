"""Right panel: grade-entry spreadsheet."""
import time
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import BONUS_MALUS_KEY, GradingScheme, GradingSettings, Student, Subquestion, compute_grade

import data_store

_HEADER_ROWS = 3        # exercise row · subquestion row · max-points row
_FROZEN_COLS = 2        # Student, Number columns are always visible

# Bounds (px) for the grading panel width computed from the table content.
_PANEL_MIN_W = 300
_PANEL_MAX_W = 700

# Cell padding (px) for normal / compact display modes.
# H_PAD: buffer (px) added to "0.0" text width for minimum column width.
#         CSS horizontal padding is kept at 0; Qt's internal style margin handles visual spacing.
# V_PAD: total vertical padding added to font height for the default row height.
#         The CSS v-padding strings in _apply_compact_mode must stay consistent with these values.
_H_PAD_NORMAL  = 0   # 0 px buffer for minimumSectionSize in normal mode
_H_PAD_COMPACT = 0   # 0 px buffer for minimumSectionSize in compact mode
_H_MINWIDTH_OFFSET_NORMAL  = 14
_H_MINWIDTH_OFFSET_COMPACT = 14
_V_PAD_NORMAL  = 8   # CSS padding-top/bottom: 2px → 4 px total + 4 px clearance
_V_PAD_COMPACT = 4   # CSS padding-top/bottom: 1px → 2 px total + 2 px clearance

# Header background colours
_BG_EX   = QColor(180, 198, 230)   # exercise name row
_BG_SQ   = QColor(210, 224, 245)   # subquestion name row
_BG_MAX  = QColor(235, 242, 252)   # max-points row
_BG_MISC = QColor(215, 215, 215)   # non-grade fixed columns (Student, Number, …)

_HIGHLIGHT_COLOR = QColor(30, 100, 220)   # border colour for the current-student row
_COL_ACTIVE_TINT = QColor(30, 100, 220, 70)  # semi-transparent tint for active column header
_SQ_HEADER_ROW = 1  # row index of the subquestion name within the header rows
_MAX_PTS_HEADER_ROW = 2  # row index of the max-points within the header rows

# Grade text colours based on percentage of max grade
_GRADE_COLOR_LOW    = QColor(180, 30, 30)    # < 40 %: dark red
_GRADE_COLOR_MID    = QColor(200, 130, 0)    # 40–50 %: darkish orange
_GRADE_COLOR_HIGH   = QColor(30, 130, 30)    # ≥ 50 %: dark green

_GRADE_THRESHOLD_MID  = 0.40   # below this → LOW (red);  at/above → MID (orange)
_GRADE_THRESHOLD_HIGH = 0.50   # below this → MID (orange); at/above → HIGH (green)


class _HighlightDelegate(QStyledItemDelegate):
    """Draws a 2-px coloured border around each cell of the highlighted row.

    The selection background is suppressed so the grade-based cell colours are
    always visible regardless of focus state.
    Also tints the subquestion-name header cell of the column being edited.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._highlight_row: int = -1
        self._highlight_col: int = -1   # column whose subquestion header is tinted
        self._editor_opened_callback = None  # optional callback(row, col)
        self._editor_closed_callback = None  # optional callback()
        self._tab_at_end_callback = None     # optional callback(row, col) → bool
        self._current_editing_row: int = -1
        self._current_editing_col: int = -1

    def set_highlight_row(self, row: int):
        self._highlight_row = row

    def set_highlight_col(self, col: int):
        self._highlight_col = col

    def set_editor_opened_callback(self, callback):
        """Set a callback invoked with (row, col) whenever an editor is created."""
        self._editor_opened_callback = callback

    def set_editor_closed_callback(self, callback):
        """Set a callback invoked whenever an editor is destroyed."""
        self._editor_closed_callback = callback

    def set_tab_at_end_callback(self, callback):
        """Set a callback invoked with (row, col) when Tab is pressed in an
        editor.  The callback should return True if it handled the navigation
        (in which case the Tab key event is consumed and the editor commits),
        or False to let Qt handle normal Tab behaviour."""
        self._tab_at_end_callback = callback

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if editor is not None:
            editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if isinstance(editor, QLineEdit):
                # Remove the default 1-px frame so the text baseline and
                # horizontal position match the non-edit cell rendering.
                editor.setFrame(False)
            # Intercept Ctrl+Z / Ctrl+Shift+Z so they cancel the in-progress
            # cell edit instead of triggering the QLineEdit's local text undo.
            editor.installEventFilter(self)
            self._current_editing_row = index.row()
            self._current_editing_col = index.column()
            if self._editor_opened_callback is not None:
                self._editor_opened_callback(index.row(), index.column())
        return editor

    def destroyEditor(self, editor, index):
        super().destroyEditor(editor, index)
        if self._editor_closed_callback is not None:
            self._editor_closed_callback()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            if event.key() == Qt.Key.Key_Z and mods in (
                Qt.KeyboardModifier.ControlModifier,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
            ):
                # Close the editor WITHOUT committing (discard the edit).
                # The next Ctrl+Z press (outside the editor) will trigger
                # the app-wide undo via the menu shortcut.
                self.closeEditor.emit(
                    obj, QStyledItemDelegate.EndEditHint.RevertModelCache,
                )
                return True
            if (event.key() == Qt.Key.Key_Tab
                    and mods == Qt.KeyboardModifier.NoModifier
                    and self._tab_at_end_callback is not None
                    and self._tab_at_end_callback(
                        self._current_editing_row, self._current_editing_col)):
                # Commit the current value and let the callback handle navigation.
                self.closeEditor.emit(
                    obj, QStyledItemDelegate.EndEditHint.SubmitModelCache,
                )
                return True
        return super().eventFilter(obj, event)

    def paint(self, painter, option: QStyleOptionViewItem, index):
        # Suppress the built-in selection fill so grade colours are not overridden.
        opt = QStyleOptionViewItem(option)
        opt.state &= ~opt.state.__class__.State_Selected
        super().paint(painter, opt, index)

        if index.row() == self._highlight_row:
            painter.save()
            painter.setPen(QPen(_HIGHLIGHT_COLOR, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            # Shrink by 1 px so the 2-px pen stays fully inside the cell
            # boundary and does not affect row height or column width.
            painter.drawRect(option.rect.adjusted(1, 1, -1, -1))
            painter.restore()

        # Tint the subquestion-name and max-points header cells for the column being edited.
        if (self._highlight_col >= 0
                and index.column() == self._highlight_col
                and index.row() in (_SQ_HEADER_ROW, _MAX_PTS_HEADER_ROW)):
            painter.save()
            painter.fillRect(option.rect, _COL_ACTIVE_TINT)
            painter.restore()


class GradingPanel(QWidget):
    grade_changed   = Signal(str, str, object, object)   # student_number, sq_name, old_value, new_value
    student_selected = Signal(object)            # Student

    def __init__(self, parent=None):
        super().__init__(parent)
        self._students: List[Student] = []
        self._scheme: Optional[GradingScheme] = None
        self._grades: Dict[str, Dict[str, float]] = {}
        self._current_student: Optional[Student] = None
        self._subquestions: List[Subquestion] = []
        self._exercises_for_sq: List[str] = []   # parallel list: exercise name per subquestion
        self._rebuilding = False
        self._show_extra = False   # whether extra CSV fields are shown
        self._grading_settings: GradingSettings = GradingSettings()
        # Track the last grading cell focused per student  {student_number: sq_name}
        self._last_focus: Dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Top bar: search + extra-fields toggle ─────────────────────────────
        top = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter students…")
        self._search.textChanged.connect(self._rebuild_table)
        top.addWidget(self._search)

        self._search_mode = QComboBox()
        self._search_mode.addItems(["Name + ID", "Name", "ID", "Annotations"])
        self._search_mode.setToolTip("Choose which field to search in")
        self._search_mode.currentIndexChanged.connect(self._on_search_mode_changed)
        top.addWidget(self._search_mode)

        clear_btn = QPushButton("✕")
        clear_btn.setToolTip("Clear filter")
        clear_btn.setFixedWidth(28)
        clear_btn.clicked.connect(self._search.clear)
        top.addWidget(clear_btn)
        layout.addLayout(top)

        self._table = QTableWidget()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # Minimum section size and default row height are set by _apply_compact_mode,
        # which is called from set_grading_settings before the table is first shown.
        # The built-in single-row header is replaced by 3 data rows at the top
        hdr.setVisible(False)
        self._table.verticalHeader().setVisible(False)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)

        # Delegate draws a border around the current student's row instead of
        # changing background colours (which would override grade colouring).
        # Each view gets its own instance so Qt's commitData signal is not
        # forwarded to a view that did not create the editor.
        self._highlight_delegate = _HighlightDelegate(self._table)
        self._highlight_delegate.set_editor_opened_callback(self._on_cell_editor_opened)
        self._highlight_delegate.set_editor_closed_callback(self._on_cell_editor_closed)
        self._highlight_delegate.set_tab_at_end_callback(self._on_tab_in_editor)
        self._table.setItemDelegate(self._highlight_delegate)

        layout.addWidget(self._table)

        # ── Frozen overlays (sticky header rows + Student/Number columns) ─────
        self._fz_corner = QTableView(self._table)
        self._fz_header = QTableView(self._table)
        self._fz_left   = QTableView(self._table)

        for fz in (self._fz_corner, self._fz_header, self._fz_left):
            fz.setModel(self._table.model())
            fz.horizontalHeader().setVisible(False)
            fz.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Fixed)
            fz.verticalHeader().setVisible(False)
            fz.verticalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Fixed)
            fz.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            fz.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            fz.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            fz.setShowGrid(True)
            fz.setSelectionMode(
                QAbstractItemView.SelectionMode.NoSelection)
            fz.setEditTriggers(
                QAbstractItemView.EditTrigger.NoEditTriggers)
            fz.setStyleSheet("QTableView { border: none; }")
            fz.hide()

        # Click on frozen left selects the student
        self._fz_left.clicked.connect(
            lambda idx: self._on_cell_clicked(idx.row(), idx.column()))
        # The frozen left panel gets its own highlight delegate (separate
        # instance avoids Qt's "commitData" warning when _table's editor closes).
        self._fz_left_highlight_delegate = _HighlightDelegate(self._fz_left)
        self._fz_left.setItemDelegate(self._fz_left_highlight_delegate)
        # The frozen header overlay also gets its own delegate so it can tint
        # the subquestion-name cell of the column being edited.
        self._fz_header_highlight_delegate = _HighlightDelegate(self._fz_header)
        self._fz_header.setItemDelegate(self._fz_header_highlight_delegate)

        # Sync scrolling: main table → frozen overlays
        self._table.horizontalScrollBar().valueChanged.connect(
            self._fz_header.horizontalScrollBar().setValue)
        self._table.verticalScrollBar().valueChanged.connect(
            self._fz_left.verticalScrollBar().setValue)

        # Re-sync column/row sizes when the main table resizes sections
        self._table.horizontalHeader().sectionResized.connect(
            self._on_frozen_section_resized)

        # Re-position overlays when the viewport resizes
        self._table.viewport().installEventFilter(self)

        # Forward wheel events from frozen overlays to the main table so that
        # scrolling over sticky headers/columns moves the main view.
        for fz in (self._fz_corner, self._fz_header, self._fz_left):
            fz.viewport().installEventFilter(self)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_session(
        self,
        students: List[Student],
        scheme: GradingScheme,
        grades: Dict[str, dict],
    ):
        self._students = students
        self._scheme = scheme
        self._grades = grades
        self._subquestions = []
        self._exercises_for_sq = []
        for ex in scheme.exercises:
            for sq in ex.subquestions:
                self._subquestions.append(sq)
                self._exercises_for_sq.append(ex.name)
        self._rebuild_table()

    def set_grading_settings(self, settings: GradingSettings):
        """Update grade-calculation settings and refresh the table."""
        self._grading_settings = settings
        if settings.show_extra_fields != self._show_extra:
            self._show_extra = settings.show_extra_fields
            self._update_search_modes()
        self._apply_compact_mode(settings.compact_table)
        self._rebuild_table()

    def _apply_compact_mode(self, smaller: bool):
        """Apply compact display (smaller font + reduced cell padding) via CSS, or restore defaults."""
        app_font = QApplication.font()
        if smaller:
            font = QFont(app_font)
            font.setPointSize(max(7, app_font.pointSize() - 2))
            v_padding = "1px"
            h_pad = _H_PAD_COMPACT
            v_pad = _V_PAD_COMPACT
            h_minwidth_offset = _H_MINWIDTH_OFFSET_COMPACT
        else:
            font = app_font
            v_padding = "2px"
            h_pad = _H_PAD_NORMAL
            v_pad = _V_PAD_NORMAL
            h_minwidth_offset = _H_MINWIDTH_OFFSET_NORMAL
            
        # Horizontal padding is kept at 0 in CSS; minimumSectionSize (below) ensures
        # columns are not too narrow. Only vertical padding is applied via CSS.
        css_item = f"padding: {v_padding} 0"
        self._table.setFont(font)
        self._table.setStyleSheet(
            f"QTableWidget::item {{ {css_item}; }}"
        )
        for fz in (self._fz_corner, self._fz_header, self._fz_left):
            fz.setFont(font)
            fz.setStyleSheet(
                f"QTableView {{ border: none; }} "
                f"QTableView::item {{ {css_item}; }}"
            )
        fm = QFontMetrics(font)
        self._table.horizontalHeader().setMinimumSectionSize(
            fm.horizontalAdvance("0.0") + h_pad + h_minwidth_offset)
        row_h = fm.height() + v_pad
        self._table.verticalHeader().setDefaultSectionSize(row_h)
        for r in range(self._table.rowCount()):
            self._table.setRowHeight(r, row_h)

    def exam_max_points(self) -> float:
        """Return the sum of all subquestion max points."""
        return self._max_total()

    def filtered_students(self) -> List[Student]:
        """Return the list of students currently visible after filtering."""
        return self._filtered_students()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _extra_field_names(self) -> List[str]:
        """Collect the union of all extra field names across all students (insertion-ordered)."""
        seen: dict = {}
        for s in self._students:
            for k in s.extra_fields:
                seen[k] = None
        return list(seen)

    def _on_search_mode_changed(self):
        """Rebuild only when the user has an active filter; otherwise a no-op."""
        if self._search.text().strip():
            self._rebuild_table()

    def _update_search_modes(self):
        """Rebuild the search-mode combo so extra-field names appear when visible."""
        current = self._search_mode.currentText()
        self._search_mode.blockSignals(True)
        self._search_mode.clear()
        base = ["Name + ID", "Name", "ID", "Annotations"]
        self._search_mode.addItems(base)
        if self._show_extra:
            for name in self._extra_field_names():
                self._search_mode.addItem(name)
        idx = self._search_mode.findText(current)
        if idx >= 0:
            self._search_mode.setCurrentIndex(idx)
        self._search_mode.blockSignals(False)

    def set_current_student(self, student: Optional[Student]):
        self._current_student = student
        self._apply_highlight()

    def focus_student_cell(self, student_number: str):
        """Focus the appropriate grading cell for *student_number*.

        • No previous edit for this student → first grading cell.
        • Last-edited cell is empty → jump back to it.
        • Last-edited cell is filled → advance to the next grading cell
          (clamped to the last grading column).
        """
        filtered = self._filtered_students()
        data_row = next(
            (i for i, s in enumerate(filtered) if s.student_number == student_number),
            -1,
        )
        if data_row < 0 or not self._subquestions:
            return

        sq_start = 2
        sq_end = sq_start + len(self._subquestions) - 1  # last grading col
        row = _HEADER_ROWS + data_row

        last_sq = self._last_focus.get(student_number)
        if last_sq and any(sq.name == last_sq for sq in self._subquestions):
            sq_idx = next(i for i, sq in enumerate(self._subquestions)
                          if sq.name == last_sq)
            col = sq_start + sq_idx
            # If the last-edited cell is non-empty, advance to the next one
            item = self._table.item(row, col)
            if item is not None and item.text().strip():
                col = min(col + 1, sq_end)
        else:
            col = sq_start   # first grading column

        self._table.setFocus()
        self._table.setCurrentCell(row, col)
        self._table.scrollToItem(
            self._table.item(row, col),
            QAbstractItemView.ScrollHint.EnsureVisible,
        )
        item = self._table.item(row, col)
        if item is not None:
            self._table.editItem(item)

    def focus_grade_cell(self, student_number: str, grade_key: str):
        """Scroll to and select the specific grade cell identified by
        *student_number* and *grade_key* (subquestion name or BONUS_MALUS_KEY).
        Used by undo/redo to make the affected cell visible."""
        filtered = self._filtered_students()
        data_row = next(
            (i for i, s in enumerate(filtered) if s.student_number == student_number),
            -1,
        )
        if data_row < 0 or not self._subquestions:
            return

        sq_start = 2
        row = _HEADER_ROWS + data_row

        if grade_key == BONUS_MALUS_KEY:
            col = sq_start + len(self._subquestions)
        else:
            sq_idx = next(
                (i for i, sq in enumerate(self._subquestions) if sq.name == grade_key),
                -1,
            )
            if sq_idx < 0:
                return
            col = sq_start + sq_idx

        self._table.setFocus()
        self._table.setCurrentCell(row, col)
        self._table.scrollToItem(
            self._table.item(row, col),
            QAbstractItemView.ScrollHint.EnsureVisible,
        )

    def preferred_width(self) -> int:
        """Return the preferred panel width based on current table column widths.

        Sums all column widths after content-based sizing, then adds frame
        borders, vertical scrollbar width, and layout margins.  The result is
        clamped between _PANEL_MIN_W and _PANEL_MAX_W.
        """
        cc = self._table.columnCount()
        if cc == 0:
            return _PANEL_MIN_W
        col_total = sum(self._table.columnWidth(c) for c in range(cc))
        if col_total == 0:
            return _PANEL_MIN_W
        fw = self._table.frameWidth()
        sb_w = self._table.verticalScrollBar().sizeHint().width()
        m = self.layout().contentsMargins()
        panel_margin = m.left() + m.right()
        preferred = col_total + fw * 2 + sb_w + panel_margin + 8  # 8 px extra breathing room
        return max(_PANEL_MIN_W, min(_PANEL_MAX_W, preferred))

    def _filtered_students(self) -> List[Student]:
        text = self._search.text().strip().lower()
        if not text:
            return list(self._students)
        mode = self._search_mode.currentText()
        result = []
        for s in self._students:
            if mode == "Name + ID":
                if (text in s.last_name.lower()
                        or text in s.first_name.lower()
                        or text in s.student_number.lower()
                        or any(text in v.lower() for v in s.extra_fields.values())):
                    result.append(s)
            elif mode == "Name":
                if (text in s.last_name.lower()
                        or text in s.first_name.lower()):
                    result.append(s)
            elif mode == "ID":
                if text in s.student_number.lower():
                    result.append(s)
            elif mode == "Annotations":
                anns = data_store.load_annotations(s.student_number)
                if any(a.text and text in a.text.lower() for a in anns):
                    result.append(s)
            else:
                # Search in a specific extra field by name
                val = s.extra_fields.get(mode, "")
                if text in val.lower():
                    result.append(s)
        return result

    def _max_total(self) -> float:
        return sum(sq.max_points for sq in self._subquestions)

    def _has_any_grade(self, sg: dict) -> bool:
        """Return True when at least one grading value has been entered.

        An all-empty row (every cell is None) is distinct from a zero score,
        and should not display a total or a grade.
        """
        return (
            any(sg.get(sq.name) is not None for sq in self._subquestions)
            or sg.get(BONUS_MALUS_KEY) is not None
        )

    def _compute_grade(self, total: float) -> float:
        """Convert raw *total* points to a final grade using current settings."""
        gs = self._grading_settings
        score_total = gs.score_total if gs.score_total is not None else self._max_total()
        return compute_grade(total, score_total, gs.max_note, gs.rounding)

    def _grade_label(self) -> str:
        """Column header label showing the max note."""
        mn = self._grading_settings.max_note
        return f"Grade\n/{mn:g}"

    def _total_label(self) -> str:
        """Column header label showing the max total score."""
        mt = self._max_total()
        return f"Tot.\n/{mt:g}"

    def _grade_color(self, val: float, max_pts: float) -> QColor:
        if max_pts <= 0:
            return QColor(255, 255, 255)
        pct = min(1.0, max(0.0, val / max_pts))
        g = int(249 + (255 - 249) * pct)
        b = int(196 + (255 - 196) * pct)
        return QColor(255, g, b)

    @staticmethod
    def _bonus_malus_color(val) -> QColor:
        if val is None or val == 0:
            return QColor(232, 232, 232)
        if val > 0:
            return QColor(200, 240, 200)
        return QColor(255, 205, 210)

    def _grade_text_color(self, grade: float) -> QColor:
        """Return text colour for a final grade based on percentage of max_note."""
        mn = self._grading_settings.max_note
        if mn <= 0:
            return QColor(0, 0, 0)
        pct = grade / mn
        if pct < _GRADE_THRESHOLD_MID:
            return _GRADE_COLOR_LOW
        if pct < _GRADE_THRESHOLD_HIGH:
            return _GRADE_COLOR_MID
        return _GRADE_COLOR_HIGH

    def _rebuild_table(self):
        t0 = time.perf_counter()
        self._rebuilding = True
        self._table.blockSignals(True)
        self._table.setUpdatesEnabled(False)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        try:
            self._build_table_contents()
        finally:
            hdr.setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents)
            self._table.setUpdatesEnabled(True)
            self._table.blockSignals(False)
            self._rebuilding = False
        t1 = time.perf_counter()
        self._apply_highlight()
        t2 = time.perf_counter()
        data_store.dbg(f"  _rebuild_table breakdown — "
                       f"build_contents: {(t1 - t0) * 1000:.1f} ms, "
                       f"apply_highlight: {(t2 - t1) * 1000:.1f} ms")
        # Defer frozen overlay update so column widths are computed first
        QTimer.singleShot(0, self._update_frozen_geometry)

    def _build_table_contents(self):
        t0 = time.perf_counter()
        filtered = self._filtered_students()
        sq_count = len(self._subquestions)
        extra_names = self._extra_field_names() if self._show_extra else []
        extra_count = len(extra_names)
        # Layout: Name | Number | subquestions… | Bonus/malus | Total | Grade/20 | [extra…]
        sq_start = 2
        bonus_col = sq_start + sq_count
        total_col = bonus_col + 1
        grade_col = bonus_col + 2
        extra_start = bonus_col + 3
        col_count = extra_start + extra_count
        # _HEADER_ROWS frozen header rows + data rows + avg row + exercise-avg row
        self._table.setRowCount(_HEADER_ROWS + len(filtered) + 2)
        self._table.setColumnCount(col_count)
        data_store.dbg(f"  _build_table_contents: {len(filtered)} rows × {col_count} cols "
                       f"({sq_count} subquestions, {extra_count} extra fields)")

        # ── Build the 3-row column header ─────────────────────────────────────
        self._table.clearSpans()

        def _hdr(text: str, bg: QColor, bold: bool = False) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it.setBackground(bg)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if bold:
                f = it.font(); f.setBold(True); it.setFont(f)
            if text:
                it.setToolTip(text.replace("\n", " "))
            return it

        # Fixed columns (Student, Number, Total, Grade/20, extras) span all 3 header rows
        fixed_cols = [0, 1, total_col, grade_col] + list(range(extra_start, extra_start + extra_count))
        fixed_labels = ["Student", "Number", self._total_label(), self._grade_label()] + extra_names
        for c, label in zip(fixed_cols, fixed_labels):
            self._table.setSpan(0, c, _HEADER_ROWS, 1)
            self._table.setItem(0, c, _hdr(label, _BG_MISC, bold=True))
            for r in (1, 2):
                self._table.setItem(r, c, _hdr("", _BG_MISC))

        # Bonus/malus column: 3-row header like grading cells (keeps column narrow)
        self._table.setItem(0, bonus_col, _hdr("", _BG_MISC))
        bm_hdr = _hdr("B/M", _BG_SQ)
        bm_hdr.setToolTip("Bonus / malus")
        self._table.setItem(1, bonus_col, bm_hdr)
        self._table.setItem(2, bonus_col, _hdr("", _BG_MAX))

        # Grade columns: group by exercise for row-0 spans
        ex_groups: Dict[str, List[int]] = {}   # exercise name → list of sq col offsets
        for ci, ex_name in enumerate(self._exercises_for_sq):
            ex_groups.setdefault(ex_name, []).append(ci)

        seen_ex: set = set()
        for ci, (ex_name, sq) in enumerate(zip(self._exercises_for_sq, self._subquestions)):
            col = sq_start + ci
            # Row 0: exercise name, merged across all sqs of that exercise
            if ex_name not in seen_ex:
                seen_ex.add(ex_name)
                span = len(ex_groups[ex_name])
                if span > 1:
                    self._table.setSpan(0, col, 1, span)
                self._table.setItem(0, col, _hdr(ex_name, _BG_EX, bold=True))
            # Row 1: subquestion name
            self._table.setItem(1, col, _hdr(sq.name, _BG_SQ))
            # Row 2: max points
            self._table.setItem(2, col, _hdr(f"/{sq.max_points:g}", _BG_MAX))

        t1 = time.perf_counter()
        data_store.dbg(f"    header built: {(t1 - t0) * 1000:.1f} ms")

        # ── Data rows ─────────────────────────────────────────────────────────
        for row_idx, student in enumerate(filtered):
            r = _HEADER_ROWS + row_idx
            sn = student.student_number
            sg = self._grades.get(sn, {})

            name_item = QTableWidgetItem(f"{student.last_name}, {student.first_name}")
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._table.setItem(r, 0, name_item)

            num_item = QTableWidgetItem(sn)
            num_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._table.setItem(r, 1, num_item)

            total = 0.0
            for col_idx, sq in enumerate(self._subquestions):
                val = sg.get(sq.name)
                item = QTableWidgetItem("" if val is None else str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if val is not None:
                    total += val
                    color = self._grade_color(val, sq.max_points)
                    if val < 0 or val > sq.max_points:
                        color = QColor(255, 205, 210)
                    item.setBackground(color)
                else:
                    item.setBackground(QColor(232, 232, 232))
                self._table.setItem(r, sq_start + col_idx, item)

            # Bonus/malus column
            bm_val = sg.get(BONUS_MALUS_KEY)
            bm_item = QTableWidgetItem("" if bm_val is None else str(bm_val))
            bm_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            bm_item.setBackground(self._bonus_malus_color(bm_val))
            if bm_val is not None:
                total += bm_val
            self._table.setItem(r, bonus_col, bm_item)

            # Only show total and grade when at least one cell is filled (not the
            # same as zero – an empty row means no grading has been entered yet).
            has_any_grade = self._has_any_grade(sg)
            total_item = QTableWidgetItem("" if not has_any_grade else f"{total:.1f}")
            total_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(r, total_col, total_item)

            grade = self._compute_grade(total) if has_any_grade else 0.0
            grade_item = QTableWidgetItem("" if not has_any_grade else f"{grade:g}")
            grade_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            grade_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if has_any_grade:
                grade_item.setForeground(self._grade_text_color(grade))
            gf = grade_item.font()
            gf.setBold(True)
            grade_item.setFont(gf)
            self._table.setItem(r, grade_col, grade_item)

            for ei, ename in enumerate(extra_names):
                val = student.extra_fields.get(ename, "")
                it = QTableWidgetItem(val)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                it.setForeground(QColor(80, 80, 80))
                self._table.setItem(r, extra_start + ei, it)

        t2 = time.perf_counter()
        data_store.dbg(f"    data rows built: {(t2 - t1) * 1000:.1f} ms")
        self._fill_average_row(filtered)
        t3 = time.perf_counter()
        data_store.dbg(f"    average rows built: {(t3 - t2) * 1000:.1f} ms")

    def _fill_average_row(self, filtered: List[Student]):
        sq_count = len(self._subquestions)
        extra_count = len(self._extra_field_names()) if self._show_extra else 0
        sq_start = 2
        bonus_col = sq_start + sq_count
        total_col = bonus_col + 1
        grade_col = bonus_col + 2
        extra_start = bonus_col + 3
        avg_row = _HEADER_ROWS + len(filtered)
        included = [
            s for s in filtered
            if self._has_any_grade(self._grades.get(s.student_number, {}))
        ]
        bold = QFont()
        bold.setBold(True)

        def _avg_item(text: str, tooltip: str = "") -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it.setFont(bold)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if tooltip:
                it.setToolTip(tooltip)
            return it

        self._table.setItem(avg_row, 0, _avg_item(f"Avg ({len(included)})"))
        self._table.setItem(avg_row, 1, _avg_item(""))
        avg_total = 0.0
        for col_idx, sq in enumerate(self._subquestions):
            if included:
                vals = [self._grades.get(s.student_number, {}).get(sq.name, 0.0) or 0.0
                        for s in included]
                avg_val = sum(vals) / len(included)
            else:
                avg_val = 0.0
            avg_total += avg_val
            self._table.setItem(avg_row, sq_start + col_idx,
                                 _avg_item(f"{avg_val:.1f}" if included else "",
                                           f"{avg_val:.3f}" if included else ""))
        # Bonus/malus average
        if included:
            bm_vals = [self._grades.get(s.student_number, {}).get(BONUS_MALUS_KEY, 0.0) or 0.0
                       for s in included]
            bm_avg = sum(bm_vals) / len(included)
        else:
            bm_avg = 0.0
        avg_total += bm_avg
        self._table.setItem(avg_row, bonus_col,
                             _avg_item(f"{bm_avg:.1f}" if included else "",
                                       f"{bm_avg:.3f}" if included else ""))
        self._table.setItem(avg_row, total_col,
                             _avg_item(f"{avg_total:.1f}" if included else "",
                                       f"{avg_total:.3f}" if included else ""))
        avg_grade = self._compute_grade(avg_total) if included else 0.0
        self._table.setItem(avg_row, grade_col,
                             _avg_item(f"{avg_grade:g}" if included else "",
                                       f"{avg_grade:.3f}" if included else ""))
        for ei in range(extra_count):
            self._table.setItem(avg_row, extra_start + ei, _avg_item(""))

        self._fill_exercise_average_row(filtered, included)

    def _fill_exercise_average_row(self, filtered: List[Student],
                                    included: List[Student]):
        """Bottom row: one merged cell per exercise showing its average score."""
        sq_count = len(self._subquestions)
        extra_count = len(self._extra_field_names()) if self._show_extra else 0
        sq_start = 2
        bonus_col = sq_start + sq_count
        total_col = bonus_col + 1
        grade_col = bonus_col + 2
        extra_start = bonus_col + 3
        ex_row = _HEADER_ROWS + len(filtered) + 1

        italic_bold = QFont()
        italic_bold.setBold(True)
        italic_bold.setItalic(True)

        def _ex_item(text: str, bg: QColor, tooltip: str = "") -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it.setFont(italic_bold)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it.setBackground(bg)
            if tooltip:
                it.setToolTip(tooltip)
            return it

        # Fixed columns
        self._table.setItem(ex_row, 0, _ex_item("Ex. avg", _BG_MISC))
        self._table.setItem(ex_row, 1, _ex_item("", _BG_MISC))
        # Bonus/malus, Total and Grade columns
        self._table.setItem(ex_row, bonus_col, _ex_item("", _BG_MISC))
        self._table.setItem(ex_row, total_col, _ex_item("", _BG_MISC))
        self._table.setItem(ex_row, grade_col, _ex_item("", _BG_MISC))
        for ei in range(extra_count):
            self._table.setItem(ex_row, extra_start + ei, _ex_item("", _BG_MISC))

        # Group subquestion column offsets by exercise (same order as header row 0)
        ex_groups: Dict[str, List[int]] = {}
        for ci, ex_name in enumerate(self._exercises_for_sq):
            ex_groups.setdefault(ex_name, []).append(ci)

        seen_ex: set = set()
        for ci, ex_name in enumerate(self._exercises_for_sq):
            if ex_name in seen_ex:
                continue
            seen_ex.add(ex_name)
            cols = ex_groups[ex_name]
            first_col = sq_start + cols[0]
            span = len(cols)

            # Average score for this exercise across included students
            if included:
                ex_avg = sum(
                    sum(
                        self._grades.get(s.student_number, {}).get(
                            self._subquestions[ci2].name, 0.0) or 0.0
                        for ci2 in cols
                    )
                    for s in included
                ) / len(included)
                ex_max = sum(self._subquestions[ci2].max_points for ci2 in cols)
                text = f"{ex_avg:.1f} / {ex_max:g}"
                tooltip = f"{ex_avg:.3f} / {ex_max:g}"
            else:
                text = ""
                tooltip = ""

            if span > 1:
                self._table.setSpan(ex_row, first_col, 1, span)
            self._table.setItem(ex_row, first_col, _ex_item(text, _BG_EX, tooltip))

    def _apply_highlight(self):
        if not self._current_student:
            self._highlight_delegate.set_highlight_row(-1)
            self._fz_left_highlight_delegate.set_highlight_row(-1)
            self._table.viewport().update()
            self._fz_left.viewport().update()
            return
        filtered = self._filtered_students()
        for row_idx, student in enumerate(filtered):
            if student.student_number == self._current_student.student_number:
                r = _HEADER_ROWS + row_idx
                self._highlight_delegate.set_highlight_row(r)
                self._fz_left_highlight_delegate.set_highlight_row(r)
                self._table.clearSelection()
                self._table.viewport().update()
                self._fz_left.viewport().update()
                # Scroll vertically to make the highlighted row visible, but
                # preserve the horizontal scroll position so the user's current
                # column stays in view.
                h_val = self._table.horizontalScrollBar().value()
                self._table.scrollToItem(
                    self._table.item(r, 0),
                    QAbstractItemView.ScrollHint.EnsureVisible,
                )
                self._table.horizontalScrollBar().setValue(h_val)
                return
        self._highlight_delegate.set_highlight_row(-1)
        self._fz_left_highlight_delegate.set_highlight_row(-1)
        self._table.viewport().update()
        self._fz_left.viewport().update()

    def _update_row_totals(self, row: int, student: Student):
        sq_count = len(self._subquestions)
        sq_start = 2
        bonus_col = sq_start + sq_count
        total_col = bonus_col + 1
        grade_col = bonus_col + 2
        sg = self._grades.get(student.student_number, {})
        has_any_grade = self._has_any_grade(sg)
        total = sum(sg.get(sq.name, 0) or 0 for sq in self._subquestions)
        total += sg.get(BONUS_MALUS_KEY, 0) or 0
        total_item = self._table.item(row, total_col)
        if total_item:
            total_item.setText("" if not has_any_grade else f"{total:.1f}")
        grade = self._compute_grade(total) if has_any_grade else 0.0
        grade_item = self._table.item(row, grade_col)
        if grade_item:
            grade_item.setText("" if not has_any_grade else f"{grade:g}")
            if has_any_grade:
                grade_item.setForeground(self._grade_text_color(grade))

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._rebuilding:
            return
        row, col = item.row(), item.column()
        # Ignore clicks on the 3 frozen header rows
        if row < _HEADER_ROWS:
            return
        data_row = row - _HEADER_ROWS
        filtered = self._filtered_students()
        if data_row >= len(filtered):
            return
        sq_start = 2
        sq_end = sq_start + len(self._subquestions)
        bonus_col = sq_end

        # Only handle subquestion columns and the bonus/malus column
        is_bonus = (col == bonus_col)
        if not is_bonus and (col < sq_start or col >= sq_end):
            return

        student = filtered[data_row]
        grade_key = BONUS_MALUS_KEY if is_bonus else self._subquestions[col - sq_start].name
        # Accept French decimal comma ("1,5" → "1.5")
        text = item.text().strip().replace(",", ".")

        if text == "":
            sg = self._grades.get(student.student_number, {})
            old_val = sg.get(grade_key)
            sg.pop(grade_key, None)
            self.grade_changed.emit(student.student_number, grade_key, old_val, None)
            self._rebuilding = True
            self._table.blockSignals(True)
            item.setBackground(QColor(232, 232, 232))
            self._update_row_totals(row, student)
            self._fill_average_row(filtered)
            self._table.blockSignals(False)
            self._rebuilding = False
            return

        # "m" / "M" → max points for this subquestion (not for bonus/malus)
        if not is_bonus and text.lower() == "m":
            text = str(self._subquestions[col - sq_start].max_points)

        try:
            val = float(text)
        except ValueError:
            prev = self._grades.get(student.student_number, {}).get(grade_key)
            self._rebuilding = True
            self._table.blockSignals(True)
            item.setText("" if prev is None else str(prev))
            self._table.blockSignals(False)
            self._rebuilding = False
            return

        old_val = self._grades.get(student.student_number, {}).get(grade_key)
        if student.student_number not in self._grades:
            self._grades[student.student_number] = {}
        self._grades[student.student_number][grade_key] = val
        # Record this cell as the last focused for this student (subquestions only)
        if not is_bonus:
            self._last_focus[student.student_number] = grade_key
        self.grade_changed.emit(student.student_number, grade_key, old_val, val)

        self._rebuilding = True
        self._table.blockSignals(True)
        # Update cell text immediately (e.g. "1,5" → "1.5")
        item.setText(str(val))
        if is_bonus:
            item.setBackground(self._bonus_malus_color(val))
        else:
            sq = self._subquestions[col - sq_start]
            color = self._grade_color(val, sq.max_points)
            if val < 0 or val > sq.max_points:
                color = QColor(255, 205, 210)
            item.setBackground(color)
        self._update_row_totals(row, student)
        self._fill_average_row(filtered)
        self._table.blockSignals(False)
        self._rebuilding = False

    def _on_cell_editor_opened(self, row: int, col: int):
        """Called whenever an editor is opened for (row, col); update _last_focus."""
        if row < _HEADER_ROWS:
            return
        data_row = row - _HEADER_ROWS
        filtered = self._filtered_students()
        if data_row >= len(filtered):
            return
        sq_start = 2
        sq_end = sq_start + len(self._subquestions)
        if sq_start <= col < sq_end:
            student = filtered[data_row]
            sq = self._subquestions[col - sq_start]
            self._last_focus[student.student_number] = sq.name
            self._set_col_highlight(col)
        else:
            self._set_col_highlight(-1)

    def _on_cell_editor_closed(self):
        """Called whenever an editor is destroyed; clear the column highlight."""
        self._set_col_highlight(-1)

    def _set_col_highlight(self, col: int):
        """Update the active-column tint on all delegates that show header rows."""
        for delegate in (self._highlight_delegate, self._fz_header_highlight_delegate):
            delegate.set_highlight_col(col)
        self._table.viewport().update()
        self._fz_header.viewport().update()

    def _on_cell_clicked(self, row: int, col: int):
        # Ignore clicks on the 3 frozen header rows
        if row < _HEADER_ROWS:
            return
        data_row = row - _HEADER_ROWS
        filtered = self._filtered_students()
        if data_row >= len(filtered):
            return
        student = filtered[data_row]
        sq_start = 2
        sq_end = sq_start + len(self._subquestions)
        bonus_col = sq_end
        if sq_start <= col < sq_end:
            sq = self._subquestions[col - sq_start]
            self._last_focus[student.student_number] = sq.name
            # Single click → enter edit mode for grading cells.
            # Deferred via singleShot so that any previously-active editor
            # is fully committed and destroyed before the new one opens.
            item = self._table.item(row, col)
            if item is not None:
                QTimer.singleShot(0, lambda captured=item: self._table.editItem(captured))
        elif col == bonus_col:
            item = self._table.item(row, col)
            if item is not None:
                QTimer.singleShot(0, lambda captured=item: self._table.editItem(captured))
        if (self._current_student is None
                or student.student_number != self._current_student.student_number):
            self.student_selected.emit(student)

    # ── Programmatic grade update (used by undo/redo) ───────────────────────

    def refresh_student_row(self, student_number: str) -> None:
        """Re-read grades for *student_number* from the shared grades dict
        and update the corresponding table row (cells, colours, totals,
        averages).  Does NOT emit ``grade_changed``."""
        filtered = self._filtered_students()
        row = -1
        student = None
        for i, s in enumerate(filtered):
            if s.student_number == student_number:
                row = _HEADER_ROWS + i
                student = s
                break
        if row < 0 or student is None:
            return
        sg = self._grades.get(student_number, {})
        sq_start = 2
        self._rebuilding = True
        self._table.blockSignals(True)
        for col_idx, sq in enumerate(self._subquestions):
            val = sg.get(sq.name)
            item = self._table.item(row, sq_start + col_idx)
            if item is None:
                continue
            item.setText("" if val is None else str(val))
            if val is not None:
                color = self._grade_color(val, sq.max_points)
                if val < 0 or val > sq.max_points:
                    color = QColor(255, 205, 210)
                item.setBackground(color)
            else:
                item.setBackground(QColor(232, 232, 232))
        # Bonus/malus column
        bonus_col = sq_start + len(self._subquestions)
        bm_val = sg.get(BONUS_MALUS_KEY)
        bm_item = self._table.item(row, bonus_col)
        if bm_item is not None:
            bm_item.setText("" if bm_val is None else str(bm_val))
            bm_item.setBackground(self._bonus_malus_color(bm_val))
        self._update_row_totals(row, student)
        self._fill_average_row(filtered)
        self._table.blockSignals(False)
        self._rebuilding = False

    # ── Frozen overlay helpers (sticky header rows + Student/Number cols) ─────

    def eventFilter(self, obj, event):
        if obj is self._table.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._update_frozen_geometry)
        # Forward wheel events from frozen overlays to the main table viewport
        # so that scrolling over sticky headers/columns stays synchronised.
        if event.type() == QEvent.Type.Wheel:
            frozen_viewports = {fz.viewport() for fz in
                                (self._fz_corner, self._fz_header, self._fz_left)}
            if obj in frozen_viewports:
                QApplication.sendEvent(self._table.viewport(), event)
                return True
        return super().eventFilter(obj, event)

    def _on_frozen_section_resized(self, idx, _old, new):
        for fz in (self._fz_corner, self._fz_header, self._fz_left):
            fz.setColumnWidth(idx, new)
        self._reposition_frozen()

    def _update_frozen_geometry(self):
        """Set up frozen overlays: hide/show cols/rows, sync sizes, position."""
        cc = self._table.columnCount()
        rc = self._table.rowCount()
        if cc < _FROZEN_COLS or rc < _HEADER_ROWS:
            for fz in (self._fz_corner, self._fz_header, self._fz_left):
                fz.hide()
            return

        # Force column width computation
        self._table.resizeColumnsToContents()

        # Sync column widths and row heights to overlays
        for c in range(cc):
            w = self._table.columnWidth(c)
            for fz in (self._fz_corner, self._fz_header, self._fz_left):
                fz.setColumnWidth(c, w)
        for r in range(rc):
            h = self._table.rowHeight(r)
            for fz in (self._fz_corner, self._fz_header, self._fz_left):
                fz.setRowHeight(r, h)

        # Corner: show only frozen cols and header rows
        for c in range(cc):
            self._fz_corner.setColumnHidden(c, c >= _FROZEN_COLS)
        for r in range(rc):
            self._fz_corner.setRowHidden(r, r >= _HEADER_ROWS)

        # Header: hide frozen cols (covered by corner), show header rows only
        for c in range(cc):
            self._fz_header.setColumnHidden(c, c < _FROZEN_COLS)
        for r in range(rc):
            self._fz_header.setRowHidden(r, r >= _HEADER_ROWS)

        # Left: show frozen cols, hide header rows (covered by corner)
        for c in range(cc):
            self._fz_left.setColumnHidden(c, c >= _FROZEN_COLS)
        for r in range(rc):
            self._fz_left.setRowHidden(r, r < _HEADER_ROWS)

        # Duplicate relevant spans on overlays
        self._set_frozen_spans()

        # Position, show, and bring to front
        self._reposition_frozen()
        for fz in (self._fz_corner, self._fz_header, self._fz_left):
            fz.show()
            fz.raise_()

        # Sync initial scroll positions
        self._fz_header.horizontalScrollBar().setValue(
            self._table.horizontalScrollBar().value())
        self._fz_left.verticalScrollBar().setValue(
            self._table.verticalScrollBar().value())

    def _set_frozen_spans(self):
        """Duplicate relevant cell spans on the frozen overlays."""
        cc = self._table.columnCount()
        sq_count = len(self._subquestions)
        sq_start = _FROZEN_COLS

        # Corner: Student and Number each span all 3 header rows
        self._fz_corner.clearSpans()
        for c in range(_FROZEN_COLS):
            self._fz_corner.setSpan(0, c, _HEADER_ROWS, 1)

        # Header: replicate the same spans as the main table for header rows
        self._fz_header.clearSpans()
        # Fixed columns that span 3 header rows (Total, Grade, extras).
        # bonus_col is intentionally excluded here: it uses a 3-row header like
        # grading cells (individual cells per row, no multi-row span).
        bonus_col = sq_start + sq_count
        for c in range(_FROZEN_COLS, cc):
            if c < sq_start or c > bonus_col:
                self._fz_header.setSpan(0, c, _HEADER_ROWS, 1)
        # Exercise name spans in row 0
        ex_groups: Dict[str, List[int]] = {}
        for ci, ex_name in enumerate(self._exercises_for_sq):
            ex_groups.setdefault(ex_name, []).append(ci)
        seen_ex: set = set()
        for ci, ex_name in enumerate(self._exercises_for_sq):
            if ex_name not in seen_ex:
                seen_ex.add(ex_name)
                span = len(ex_groups[ex_name])
                if span > 1:
                    self._fz_header.setSpan(0, sq_start + ci, 1, span)

        # Left: no spans needed (only 2 plain-text columns)
        self._fz_left.clearSpans()

    def _reposition_frozen(self):
        """Reposition frozen overlays based on current column/row sizes."""
        cc = self._table.columnCount()
        rc = self._table.rowCount()
        if cc < _FROZEN_COLS or rc < _HEADER_ROWS:
            return

        frozen_w = sum(self._table.columnWidth(c) for c in range(_FROZEN_COLS))
        frozen_h = sum(self._table.rowHeight(r) for r in range(_HEADER_ROWS))
        vp = self._table.viewport()
        fw = self._table.frameWidth()

        self._fz_corner.setGeometry(fw, fw, frozen_w, frozen_h)
        self._fz_header.setGeometry(
            fw + frozen_w, fw, vp.width() - frozen_w, frozen_h)
        self._fz_left.setGeometry(
            fw, fw + frozen_h, frozen_w, vp.height() - frozen_h)
