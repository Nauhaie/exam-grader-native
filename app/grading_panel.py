"""Right panel: grade-entry spreadsheet."""
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import GradingScheme, Student, Subquestion

GRADE_SCALE  = 20   # French 0–20 grading system
_HEADER_ROWS = 3    # exercise row · subquestion row · max-points row

# Header background colours
_BG_EX   = QColor(180, 198, 230)   # exercise name row
_BG_SQ   = QColor(210, 224, 245)   # subquestion name row
_BG_MAX  = QColor(235, 242, 252)   # max-points row
_BG_MISC = QColor(215, 215, 215)   # non-grade fixed columns (Student, Number, …)


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
        # Track the last grading cell focused per student  {student_number: sq_name}
        self._last_focus: Dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Top bar: search + extra-fields toggle ─────────────────────────────
        top = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter students by name or number…")
        self._search.textChanged.connect(self._rebuild_table)
        top.addWidget(self._search)

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
        layout.addWidget(self._table)

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

        extra_count = len(self._extra_field_names()) if self._show_extra else 0
        sq_start = 2 + extra_count
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

    # ── Internal ──────────────────────────────────────────────────────────────

    def _filtered_students(self) -> List[Student]:
        text = self._search.text().strip().lower()
        if not text:
            return list(self._students)
        return [
            s for s in self._students
            if text in s.last_name.lower()
            or text in s.first_name.lower()
            or text in s.student_number.lower()
            or any(text in v.lower() for v in s.extra_fields.values())
        ]

    def _max_total(self) -> float:
        return sum(sq.max_points for sq in self._subquestions)

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

    def _build_table_contents(self):
        filtered = self._filtered_students()
        sq_count = len(self._subquestions)
        extra_names = self._extra_field_names() if self._show_extra else []
        extra_count = len(extra_names)
        # Layout: Name | Number | [extra…] | subquestions… | Total | Grade/20
        sq_start = 2 + extra_count
        col_count = sq_start + sq_count + 2
        # _HEADER_ROWS frozen header rows + data rows + 1 average row
        self._table.setRowCount(_HEADER_ROWS + len(filtered) + 1)
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

        # Fixed columns (Student, Number, extras, Total, Grade/20) span all 3 header rows
        fixed_cols = list(range(2 + extra_count)) + [sq_start + sq_count, sq_start + sq_count + 1]
        fixed_labels = ["Student", "Number"] + extra_names + ["Total", "Grade /20"]
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
                self._table.setSpan(0, col, 1, span)
                self._table.setItem(0, col, _hdr(ex_name, _BG_EX, bold=True))
            # Row 1: subquestion name
            self._table.setItem(1, col, _hdr(sq.name, _BG_SQ))
            # Row 2: max points
            self._table.setItem(2, col, _hdr(f"/{sq.max_points:g}", _BG_MAX))

        # ── Data rows ─────────────────────────────────────────────────────────
        max_total = self._max_total()
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

            for ei, ename in enumerate(extra_names):
                val = student.extra_fields.get(ename, "")
                it = QTableWidgetItem(val)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                it.setForeground(QColor(80, 80, 80))
                self._table.setItem(r, 2 + ei, it)

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

            grade = round((total / max_total) * GRADE_SCALE, 1) if max_total > 0 else 0.0
            grade_item = QTableWidgetItem(f"{grade:.1f}")
            grade_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            grade_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(r, sq_start + sq_count + 1, grade_item)

        self._fill_average_row(filtered)

    def _fill_average_row(self, filtered: List[Student]):
        sq_count = len(self._subquestions)
        extra_count = len(self._extra_field_names()) if self._show_extra else 0
        sq_start = 2 + extra_count
        avg_row = _HEADER_ROWS + len(filtered)
        max_total = self._max_total()
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
        for ei in range(extra_count):
            self._table.setItem(avg_row, 2 + ei, _avg_item(""))
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
        avg_grade = (
            round((avg_total / max_total) * GRADE_SCALE, 1)
            if max_total > 0 and included else 0.0
        )
        self._table.setItem(avg_row, sq_start + sq_count + 1,
                             _avg_item(f"{avg_grade:.1f}" if included else ""))

    def _apply_highlight(self):
        if not self._current_student:
            return
        filtered = self._filtered_students()
        for row_idx, student in enumerate(filtered):
            if student.student_number == self._current_student.student_number:
                r = _HEADER_ROWS + row_idx
                self._table.selectRow(r)
                self._table.scrollToItem(
                    self._table.item(r, 0),
                    QAbstractItemView.ScrollHint.EnsureVisible,
                )
                return

    def _update_row_totals(self, row: int, student: Student):
        sq_count = len(self._subquestions)
        extra_count = len(self._extra_field_names()) if self._show_extra else 0
        sq_start = 2 + extra_count
        max_total = self._max_total()
        sg = self._grades.get(student.student_number, {})
        total = sum(sg.get(sq.name, 0) for sq in self._subquestions)
        total_item = self._table.item(row, sq_start + sq_count)
        if total_item:
            total_item.setText(f"{total:.1f}")
        grade = round((total / max_total) * GRADE_SCALE, 1) if max_total > 0 else 0.0
        grade_item = self._table.item(row, sq_start + sq_count + 1)
        if grade_item:
            grade_item.setText(f"{grade:.1f}")

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
        extra_count = len(self._extra_field_names()) if self._show_extra else 0
        sq_start = 2 + extra_count
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
        extra_count = len(self._extra_field_names()) if self._show_extra else 0
        sq_start = 2 + extra_count
        sq_end = sq_start + len(self._subquestions)
        if sq_start <= col < sq_end:
            sq = self._subquestions[col - sq_start]
            self._last_focus[student.student_number] = sq.name
        if (self._current_student is None
                or student.student_number != self._current_student.student_number):
            self.student_selected.emit(student)
