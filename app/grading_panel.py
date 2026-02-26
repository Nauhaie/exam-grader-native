"""Right panel: grade-entry spreadsheet."""
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLineEdit,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import GradingScheme, Student, Subquestion

GRADE_SCALE = 20  # French 0–20 grading system


class _FrozenColumnTableWidget(QTableWidget):
    """
    A QTableWidget whose first two columns are always visible (frozen/sticky).

    The frozen columns are rendered in an overlay QTableView that sits in the
    left viewport margin, so the scrollable area starts at column 2.
    """

    _N_FROZEN = 2
    frozen_row_clicked = Signal(int)  # logical row index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.verticalHeader().setVisible(False)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        # Frozen overlay: shows only the first _N_FROZEN columns
        self._fv = QTableView(self)
        self._fv.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fv.verticalHeader().setVisible(False)
        self._fv.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fv.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fv.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._fv.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._fv.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._fv.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._fv.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._fv.clicked.connect(
            lambda idx: self.frozen_row_clicked.emit(idx.row())
        )

        # Keep vertical scroll positions in sync
        self.verticalScrollBar().valueChanged.connect(
            self._fv.verticalScrollBar().setValue
        )
        self._fv.verticalScrollBar().valueChanged.connect(
            self.verticalScrollBar().setValue
        )

        # Mirror row-height changes to the frozen view
        self.verticalHeader().sectionResized.connect(
            lambda row, _old, new_h: self._fv.setRowHeight(row, new_h)
        )

    def refresh_frozen(self):
        """
        Synchronise the frozen overlay with the main table.
        Call after every full table rebuild (setRowCount / setItem / …).
        """
        model = self.model()
        if self._fv.model() is None:
            self._fv.setModel(model)

        # In the main table hide the frozen cols; in the overlay show only them
        for col in range(model.columnCount()):
            frozen = col < self._N_FROZEN
            self.setColumnHidden(col, frozen)
            self._fv.setColumnHidden(col, not frozen)

        # Let the overlay measure its own column widths from the model data
        self._fv.resizeColumnsToContents()

        # Sync row heights from the main table to the overlay
        for row in range(self.rowCount()):
            self._fv.setRowHeight(row, self.rowHeight(row))

        self._update_frozen_geometry()
        self._fv.show()

    # ── geometry helpers ──────────────────────────────────────────────────────

    def _frozen_cols_width(self) -> int:
        return sum(self._fv.columnWidth(c) for c in range(self._N_FROZEN))

    def _update_frozen_geometry(self):
        fw = self.frameWidth()
        frozen_w = self._frozen_cols_width()
        header_h = self.horizontalHeader().height()

        # Push the main scroll viewport to the right of the frozen area
        self.setViewportMargins(frozen_w, 0, 0, 0)

        # Position the frozen overlay in the left margin (outside the viewport)
        self._fv.setGeometry(
            fw,
            fw,
            frozen_w,
            self.viewport().height() + header_h,
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_frozen_geometry()


class GradingPanel(QWidget):
    grade_changed = Signal(str, str, float)  # student_number, subquestion_name, points
    student_selected = Signal(object)        # Student

    def __init__(self, parent=None):
        super().__init__(parent)
        self._students: List[Student] = []
        self._scheme: Optional[GradingScheme] = None
        self._grades: Dict[str, Dict[str, float]] = {}
        self._current_student: Optional[Student] = None
        self._subquestions: List[Subquestion] = []
        self._rebuilding = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter students by name or number…")
        self._search.textChanged.connect(self._rebuild_table)
        layout.addWidget(self._search)

        self._table = _FrozenColumnTableWidget()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.frozen_row_clicked.connect(self._on_frozen_row_clicked)
        layout.addWidget(self._table)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_session(self, students: List[Student], scheme: GradingScheme, grades: Dict[str, dict]):
        self._students = students
        self._scheme = scheme
        self._grades = grades
        self._subquestions = [sq for ex in scheme.exercises for sq in ex.subquestions]
        self._rebuild_table()

    def set_current_student(self, student: Optional[Student]):
        self._current_student = student
        self._apply_highlight()

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
        self._table.refresh_frozen()

    def _build_table_contents(self):
        filtered = self._filtered_students()
        sq_count = len(self._subquestions)
        col_count = 2 + sq_count + 2  # Name, Number, subquestions, Total, Grade/20
        self._table.setRowCount(len(filtered) + 1)  # +1 for average row
        self._table.setColumnCount(col_count)

        headers = ["Student", "Number"]
        for sq in self._subquestions:
            headers.append(f"{sq.name}\n/{sq.max_points}")
        headers += ["Total", "Grade /20"]
        self._table.setHorizontalHeaderLabels(headers)

        max_total = self._max_total()

        for row_idx, student in enumerate(filtered):
            sn = student.student_number
            sg = self._grades.get(sn, {})

            name_item = QTableWidgetItem(f"{student.last_name}, {student.first_name}")
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._table.setItem(row_idx, 0, name_item)

            num_item = QTableWidgetItem(sn)
            num_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._table.setItem(row_idx, 1, num_item)

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
                self._table.setItem(row_idx, 2 + col_idx, item)

            total_item = QTableWidgetItem(f"{total:.1f}")
            total_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row_idx, 2 + sq_count, total_item)

            grade = round((total / max_total) * GRADE_SCALE, 1) if max_total > 0 else 0.0
            grade_item = QTableWidgetItem(f"{grade:.1f}")
            grade_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            grade_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row_idx, 2 + sq_count + 1, grade_item)

        self._fill_average_row(filtered)

    def _fill_average_row(self, filtered: List[Student]):
        sq_count = len(self._subquestions)
        avg_row = len(filtered)
        max_total = self._max_total()

        included = [
            s for s in filtered
            if any(self._grades.get(s.student_number, {}).get(sq.name) is not None
                   for sq in self._subquestions)
        ]

        bold_font = QFont()
        bold_font.setBold(True)

        def _avg_item(text: str) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it.setFont(bold_font)
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
            self._table.setItem(avg_row, 2 + col_idx,
                                 _avg_item(f"{avg_val:.1f}" if included else ""))

        self._table.setItem(avg_row, 2 + sq_count,
                             _avg_item(f"{avg_total:.1f}" if included else ""))
        avg_grade = round((avg_total / max_total) * GRADE_SCALE, 1) if (max_total > 0 and included) else 0.0
        self._table.setItem(avg_row, 2 + sq_count + 1,
                             _avg_item(f"{avg_grade:.1f}" if included else ""))

    def _apply_highlight(self):
        if not self._current_student:
            return
        filtered = self._filtered_students()
        for row_idx, student in enumerate(filtered):
            is_current = student.student_number == self._current_student.student_number
            for col in range(self._table.columnCount()):
                item = self._table.item(row_idx, col)
                if item:
                    f = item.font()
                    f.setBold(is_current)
                    item.setFont(f)

    def _update_row_totals(self, row: int, student: Student):
        sq_count = len(self._subquestions)
        max_total = self._max_total()
        sg = self._grades.get(student.student_number, {})
        total = sum(sg.get(sq.name, 0) for sq in self._subquestions)

        total_item = self._table.item(row, 2 + sq_count)
        if total_item:
            total_item.setText(f"{total:.1f}")
        grade = round((total / max_total) * GRADE_SCALE, 1) if max_total > 0 else 0.0
        grade_item = self._table.item(row, 2 + sq_count + 1)
        if grade_item:
            grade_item.setText(f"{grade:.1f}")

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._rebuilding:
            return
        row = item.row()
        col = item.column()
        filtered = self._filtered_students()
        if row >= len(filtered):
            return
        sq_start = 2
        sq_end = 2 + len(self._subquestions)
        if col < sq_start or col >= sq_end:
            return

        sq = self._subquestions[col - sq_start]
        student = filtered[row]
        text = item.text().strip()

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
        filtered = self._filtered_students()
        if row >= len(filtered):
            return
        student = filtered[row]
        if self._current_student is None or student.student_number != self._current_student.student_number:
            self.student_selected.emit(student)

    def _on_frozen_row_clicked(self, row: int):
        self._on_cell_clicked(row, 0)
