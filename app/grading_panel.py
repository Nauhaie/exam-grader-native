"""Right panel: grade-entry spreadsheet."""
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
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

from models import GradingScheme, GradingSettings, Student, Subquestion

import data_store

_HEADER_ROWS = 3        # exercise row · subquestion row · max-points row
_FROZEN_COLS = 2        # Student, Number columns are always visible
_MIN_ROUNDING_STEP = 0.001   # prevents division-by-zero in grade rounding

# Header background colours
_BG_EX   = QColor(180, 198, 230)   # exercise name row
_BG_SQ   = QColor(210, 224, 245)   # subquestion name row
_BG_MAX  = QColor(235, 242, 252)   # max-points row
_BG_MISC = QColor(215, 215, 215)   # non-grade fixed columns (Student, Number, …)

_HIGHLIGHT_COLOR = QColor(30, 100, 220)   # border colour for the current-student row


class _HighlightDelegate(QStyledItemDelegate):
    """Draws a 2-px coloured border around each cell of the highlighted row.

    The selection background is suppressed so the grade-based cell colours are
    always visible regardless of focus state.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._highlight_row: int = -1

    def set_highlight_row(self, row: int):
        self._highlight_row = row

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


class GradingPanel(QWidget):
    grade_changed   = Signal(str, str, float)   # student_number, sq_name, points
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
        self._search_mode.currentIndexChanged.connect(self._rebuild_table)
        top.addWidget(self._search_mode)

        clear_btn = QPushButton("✕")
        clear_btn.setToolTip("Clear filter")
        clear_btn.setFixedWidth(28)
        clear_btn.clicked.connect(self._search.clear)
        top.addWidget(clear_btn)

        self._extra_cb = QCheckBox("Extra fields")
        self._extra_cb.setToolTip("Show/hide additional CSV columns")
        self._extra_cb.setChecked(False)
        self._extra_cb.toggled.connect(self._on_extra_toggled)
        top.addWidget(self._extra_cb)
        layout.addLayout(top)

        self._table = QTableWidget()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # The built-in single-row header is replaced by 3 data rows at the top
        hdr.setVisible(False)
        self._table.verticalHeader().setVisible(False)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)

        # Delegate draws a border around the current student's row instead of
        # changing background colours (which would override grade colouring).
        self._highlight_delegate = _HighlightDelegate(self._table)
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
        # The frozen left panel also gets the highlight delegate so the border
        # shows on the Name/Number columns too.
        self._fz_left.setItemDelegate(self._highlight_delegate)

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
        # Enable / disable the extra-fields checkbox based on data availability
        self._extra_cb.setEnabled(bool(self._extra_field_names()))
        self._rebuild_table()

    def set_grading_settings(self, settings: GradingSettings):
        """Update grade-calculation settings and refresh the table."""
        self._grading_settings = settings
        self._rebuild_table()

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

    def _on_extra_toggled(self, checked: bool):
        self._show_extra = checked
        self._rebuild_table()

    def set_current_student(self, student: Optional[Student]):
        self._current_student = student
        self._apply_highlight()

    def focus_student_cell(self, student_number: str):
        """Focus the appropriate grading cell for *student_number*.

        If a cell was previously edited for this student, return to it.
        Otherwise focus the first grading column.
        """
        filtered = self._filtered_students()
        data_row = next(
            (i for i, s in enumerate(filtered) if s.student_number == student_number),
            -1,
        )
        if data_row < 0 or not self._subquestions:
            return

        sq_start = 2
        row = _HEADER_ROWS + data_row

        last_sq = self._last_focus.get(student_number)
        if last_sq and any(sq.name == last_sq for sq in self._subquestions):
            col = sq_start + next(i for i, sq in enumerate(self._subquestions)
                                  if sq.name == last_sq)
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
        return result

    def _max_total(self) -> float:
        return sum(sq.max_points for sq in self._subquestions)

    def _compute_grade(self, total: float) -> float:
        """Convert raw *total* points to a final grade using current settings."""
        gs = self._grading_settings
        score_total = gs.score_total if gs.score_total is not None else self._max_total()
        if score_total <= 0:
            return 0.0
        raw = (total / score_total) * gs.max_note
        step = max(_MIN_ROUNDING_STEP, gs.rounding)
        return round(raw / step) * step

    def _grade_label(self) -> str:
        """Column header label showing the max note."""
        mn = self._grading_settings.max_note
        return f"Grade /{mn:g}"

    def _grade_color(self, val: float, max_pts: float) -> QColor:
        if max_pts <= 0:
            return QColor(255, 255, 255)
        pct = min(1.0, max(0.0, val / max_pts))
        g = int(249 + (255 - 249) * pct)
        b = int(196 + (255 - 196) * pct)
        return QColor(255, g, b)

    def _rebuild_table(self):
        self._rebuilding = True
        self._table.blockSignals(True)
        try:
            self._build_table_contents()
        finally:
            self._table.blockSignals(False)
            self._rebuilding = False
        self._apply_highlight()
        # Defer frozen overlay update so column widths are computed first
        QTimer.singleShot(0, self._update_frozen_geometry)

    def _build_table_contents(self):
        filtered = self._filtered_students()
        sq_count = len(self._subquestions)
        extra_names = self._extra_field_names() if self._show_extra else []
        extra_count = len(extra_names)
        # Layout: Name | Number | subquestions… | Total | Grade/20 | [extra…]
        sq_start = 2
        extra_start = sq_start + sq_count + 2
        col_count = extra_start + extra_count
        # _HEADER_ROWS frozen header rows + data rows + avg row + exercise-avg row
        self._table.setRowCount(_HEADER_ROWS + len(filtered) + 2)
        self._table.setColumnCount(col_count)

        # ── Build the 3-row column header ─────────────────────────────────────
        self._table.clearSpans()

        def _hdr(text: str, bg: QColor, bold: bool = False) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it.setBackground(bg)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if bold:
                f = it.font(); f.setBold(True); it.setFont(f)
            return it

        # Fixed columns (Student, Number, Total, Grade/20, extras) span all 3 header rows
        fixed_cols = [0, 1, sq_start + sq_count, sq_start + sq_count + 1] + list(range(extra_start, extra_start + extra_count))
        fixed_labels = ["Student", "Number", "Total", self._grade_label()] + extra_names
        for c, label in zip(fixed_cols, fixed_labels):
            self._table.setSpan(0, c, _HEADER_ROWS, 1)
            self._table.setItem(0, c, _hdr(label, _BG_MISC, bold=True))
            for r in (1, 2):
                self._table.setItem(r, c, _hdr("", _BG_MISC))

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
                    if val > sq.max_points:
                        color = QColor(255, 205, 210)
                    item.setBackground(color)
                else:
                    item.setBackground(QColor(232, 232, 232))
                self._table.setItem(r, sq_start + col_idx, item)

            total_item = QTableWidgetItem(f"{total:.1f}")
            total_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(r, sq_start + sq_count, total_item)

            grade = self._compute_grade(total)
            grade_item = QTableWidgetItem(f"{grade:g}")
            grade_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            grade_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(r, sq_start + sq_count + 1, grade_item)

            for ei, ename in enumerate(extra_names):
                val = student.extra_fields.get(ename, "")
                it = QTableWidgetItem(val)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                it.setForeground(QColor(80, 80, 80))
                self._table.setItem(r, extra_start + ei, it)

        self._fill_average_row(filtered)

    def _fill_average_row(self, filtered: List[Student]):
        sq_count = len(self._subquestions)
        extra_count = len(self._extra_field_names()) if self._show_extra else 0
        sq_start = 2
        extra_start = sq_start + sq_count + 2
        avg_row = _HEADER_ROWS + len(filtered)
        included = [
            s for s in filtered
            if any(
                self._grades.get(s.student_number, {}).get(sq.name) is not None
                for sq in self._subquestions
            )
        ]
        bold = QFont()
        bold.setBold(True)

        def _avg_item(text: str) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it.setFont(bold)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            return it

        self._table.setItem(avg_row, 0, _avg_item(f"Avg ({len(included)})"))
        self._table.setItem(avg_row, 1, _avg_item(""))
        avg_total = 0.0
        for col_idx, sq in enumerate(self._subquestions):
            if included:
                vals = [self._grades.get(s.student_number, {}).get(sq.name, 0.0)
                        for s in included]
                avg_val = sum(vals) / len(included)
            else:
                avg_val = 0.0
            avg_total += avg_val
            self._table.setItem(avg_row, sq_start + col_idx,
                                 _avg_item(f"{avg_val:.1f}" if included else ""))
        self._table.setItem(avg_row, sq_start + sq_count,
                             _avg_item(f"{avg_total:.1f}" if included else ""))
        avg_grade = self._compute_grade(avg_total) if included else 0.0
        self._table.setItem(avg_row, sq_start + sq_count + 1,
                             _avg_item(f"{avg_grade:g}" if included else ""))
        for ei in range(extra_count):
            self._table.setItem(avg_row, extra_start + ei, _avg_item(""))

        self._fill_exercise_average_row(filtered, included)

    def _fill_exercise_average_row(self, filtered: List[Student],
                                    included: List[Student]):
        """Bottom row: one merged cell per exercise showing its average score."""
        sq_count = len(self._subquestions)
        extra_count = len(self._extra_field_names()) if self._show_extra else 0
        sq_start = 2
        extra_start = sq_start + sq_count + 2
        ex_row = _HEADER_ROWS + len(filtered) + 1

        italic_bold = QFont()
        italic_bold.setBold(True)
        italic_bold.setItalic(True)

        def _ex_item(text: str, bg: QColor) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it.setFont(italic_bold)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it.setBackground(bg)
            return it

        # Fixed columns
        self._table.setItem(ex_row, 0, _ex_item("Ex. avg", _BG_MISC))
        self._table.setItem(ex_row, 1, _ex_item("", _BG_MISC))
        # Total and Grade columns
        self._table.setItem(ex_row, sq_start + sq_count,   _ex_item("", _BG_MISC))
        self._table.setItem(ex_row, sq_start + sq_count + 1, _ex_item("", _BG_MISC))
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
                            self._subquestions[ci2].name, 0.0)
                        for ci2 in cols
                    )
                    for s in included
                ) / len(included)
                ex_max = sum(self._subquestions[ci2].max_points for ci2 in cols)
                text = f"{ex_avg:.1f} / {ex_max:g}"
            else:
                text = ""

            if span > 1:
                self._table.setSpan(ex_row, first_col, 1, span)
            self._table.setItem(ex_row, first_col, _ex_item(text, _BG_EX))

    def _apply_highlight(self):
        if not self._current_student:
            self._highlight_delegate.set_highlight_row(-1)
            self._table.viewport().update()
            self._fz_left.viewport().update()
            return
        filtered = self._filtered_students()
        for row_idx, student in enumerate(filtered):
            if student.student_number == self._current_student.student_number:
                r = _HEADER_ROWS + row_idx
                self._highlight_delegate.set_highlight_row(r)
                self._table.clearSelection()
                self._table.viewport().update()
                self._fz_left.viewport().update()
                self._table.scrollToItem(
                    self._table.item(r, 0),
                    QAbstractItemView.ScrollHint.EnsureVisible,
                )
                return
        self._highlight_delegate.set_highlight_row(-1)
        self._table.viewport().update()
        self._fz_left.viewport().update()

    def _update_row_totals(self, row: int, student: Student):
        sq_count = len(self._subquestions)
        sq_start = 2
        sg = self._grades.get(student.student_number, {})
        total = sum(sg.get(sq.name, 0) for sq in self._subquestions)
        total_item = self._table.item(row, sq_start + sq_count)
        if total_item:
            total_item.setText(f"{total:.1f}")
        grade = self._compute_grade(total)
        grade_item = self._table.item(row, sq_start + sq_count + 1)
        if grade_item:
            grade_item.setText(f"{grade:g}")

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
        if col < sq_start or col >= sq_end:
            return

        sq = self._subquestions[col - sq_start]
        student = filtered[data_row]
        # Accept French decimal comma ("1,5" → "1.5")
        text = item.text().strip().replace(",", ".")

        if text == "":
            sg = self._grades.get(student.student_number, {})
            sg.pop(sq.name, None)
            data_store.save_grades(self._grades)
            self._rebuilding = True
            self._table.blockSignals(True)
            item.setBackground(QColor(232, 232, 232))
            self._update_row_totals(row, student)
            self._fill_average_row(filtered)
            self._table.blockSignals(False)
            self._rebuilding = False
            return

        try:
            val = float(text)
            if val < 0:
                raise ValueError("negative")
        except ValueError:
            prev = self._grades.get(student.student_number, {}).get(sq.name)
            self._rebuilding = True
            self._table.blockSignals(True)
            item.setText("" if prev is None else str(prev))
            self._table.blockSignals(False)
            self._rebuilding = False
            return

        if student.student_number not in self._grades:
            self._grades[student.student_number] = {}
        self._grades[student.student_number][sq.name] = val
        # Record this cell as the last focused for this student
        self._last_focus[student.student_number] = sq.name
        self.grade_changed.emit(student.student_number, sq.name, val)

        self._rebuilding = True
        self._table.blockSignals(True)
        color = self._grade_color(val, sq.max_points)
        if val > sq.max_points:
            color = QColor(255, 205, 210)
        item.setBackground(color)
        self._update_row_totals(row, student)
        self._fill_average_row(filtered)
        self._table.blockSignals(False)
        self._rebuilding = False

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
        if sq_start <= col < sq_end:
            sq = self._subquestions[col - sq_start]
            self._last_focus[student.student_number] = sq.name
        if (self._current_student is None
                or student.student_number != self._current_student.student_number):
            self.student_selected.emit(student)

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
        # Fixed columns that span 3 header rows (Total, Grade, extras)
        for c in range(_FROZEN_COLS, cc):
            if c < sq_start or c >= sq_start + sq_count:
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

        self._fz_corner.setGeometry(0, 0, frozen_w, frozen_h)
        self._fz_header.setGeometry(
            frozen_w, 0, vp.width() - frozen_w, frozen_h)
        self._fz_left.setGeometry(
            0, frozen_h, frozen_w, vp.height() - frozen_h)
