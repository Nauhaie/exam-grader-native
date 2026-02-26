"""Left panel: student list with search."""
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from models import Student


class StudentListPanel(QWidget):
    student_selected = Signal(Student)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._students: List[Student] = []
        self._filtered: List[Student] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by name or number…")
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

    def set_students(self, students: List[Student]):
        self._students = students
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str):
        text = text.lower()
        self._filtered = [
            s for s in self._students
            if text in s.last_name.lower()
            or text in s.first_name.lower()
            or text in s.student_number.lower()
        ]
        self._list.blockSignals(True)
        self._list.clear()
        for s in self._filtered:
            item = QListWidgetItem(s.display_name())
            self._list.addItem(item)
        self._list.blockSignals(False)
        # Re-select first if any
        if self._filtered:
            self._list.setCurrentRow(0)
            self.student_selected.emit(self._filtered[0])
        else:
            self.student_selected.emit(None)

    def _on_row_changed(self, row: int):
        if 0 <= row < len(self._filtered):
            self.student_selected.emit(self._filtered[row])

    def select_student(self, student: Student):
        """Programmatically select a student."""
        for i, s in enumerate(self._filtered):
            if s.student_number == student.student_number:
                self._list.setCurrentRow(i)
                return

    def current_student(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._filtered):
            return self._filtered[row]
        return None

    def mark_graded(self, student_number: str, graded: bool):
        """Bold the item if graded."""
        for i, s in enumerate(self._filtered):
            if s.student_number == student_number:
                item = self._list.item(i)
                if item:
                    font = item.font()
                    font.setBold(graded)
                    item.setFont(font)
                break
