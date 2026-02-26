"""Setup dialog: choose exam dir, students CSV, grading scheme JSON."""
import os

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

import data_store


class SetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exam Grader — Setup")
        self.setMinimumWidth(520)

        self._exams_dir = ""
        self._students_csv = ""
        self._grading_scheme = ""

        # Pre-fill from saved session config
        config = data_store.load_session_config()
        if config:
            self._exams_dir = config.get("exams_dir", "")
            self._students_csv = config.get("students_csv", "")
            self._grading_scheme = config.get("grading_scheme", "")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>Welcome to Exam Grader</b><br>"
            "Please select your exam files to get started."
        ))
        layout.addSpacing(8)

        form = QFormLayout()
        layout.addLayout(form)

        # Exams directory
        self._exams_dir_edit = QLineEdit(self._exams_dir)
        exams_btn = QPushButton("Browse…")
        exams_btn.clicked.connect(self._browse_exams_dir)
        exams_row = QHBoxLayout()
        exams_row.addWidget(self._exams_dir_edit)
        exams_row.addWidget(exams_btn)
        form.addRow("Exams directory:", exams_row)

        # Students CSV
        self._students_csv_edit = QLineEdit(self._students_csv)
        csv_btn = QPushButton("Browse…")
        csv_btn.clicked.connect(self._browse_students_csv)
        csv_row = QHBoxLayout()
        csv_row.addWidget(self._students_csv_edit)
        csv_row.addWidget(csv_btn)
        form.addRow("Students CSV:", csv_row)

        # Grading scheme JSON
        self._grading_scheme_edit = QLineEdit(self._grading_scheme)
        json_btn = QPushButton("Browse…")
        json_btn.clicked.connect(self._browse_grading_scheme)
        json_row = QHBoxLayout()
        json_row.addWidget(self._grading_scheme_edit)
        json_row.addWidget(json_btn)
        form.addRow("Grading scheme JSON:", json_row)

        layout.addSpacing(12)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: red;")
        layout.addWidget(self._error_label)

        # Buttons
        buttons = QDialogButtonBox()
        self._start_btn = buttons.addButton("Start Grading", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_exams_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Exams Directory")
        if path:
            self._exams_dir_edit.setText(path)

    def _browse_students_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Students CSV", "", "CSV files (*.csv)"
        )
        if path:
            self._students_csv_edit.setText(path)

    def _browse_grading_scheme(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Grading Scheme", "", "JSON files (*.json)"
        )
        if path:
            self._grading_scheme_edit.setText(path)

    def _on_accept(self):
        exams_dir = self._exams_dir_edit.text().strip()
        students_csv = self._students_csv_edit.text().strip()
        grading_scheme = self._grading_scheme_edit.text().strip()

        if not os.path.isdir(exams_dir):
            self._error_label.setText("Exams directory does not exist.")
            return
        if not os.path.isfile(students_csv):
            self._error_label.setText("Students CSV file not found.")
            return
        if not os.path.isfile(grading_scheme):
            self._error_label.setText("Grading scheme JSON file not found.")
            return

        data_store.save_session_config(exams_dir, students_csv, grading_scheme)
        self._exams_dir = exams_dir
        self._students_csv = students_csv
        self._grading_scheme = grading_scheme
        self.accept()

    # Public getters
    def exams_dir(self) -> str:
        return self._exams_dir

    def students_csv(self) -> str:
        return self._students_csv

    def grading_scheme(self) -> str:
        return self._grading_scheme
