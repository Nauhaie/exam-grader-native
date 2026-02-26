"""Setup dialog: choose a single project directory."""
import os

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

import data_store


class SetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exam Grader — Open Project")
        self.setMinimumWidth(540)

        self._project_dir = ""

        # Pre-fill from saved session config
        config = data_store.load_session_config()
        if config:
            self._project_dir = config.get("project_dir", "")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>Welcome to Exam Grader</b><br>"
            "Select your project directory to get started.<br><br>"
            "The project directory must contain:<br>"
            "&nbsp;&nbsp;• <tt>exams/</tt> — one PDF per student, named "
            "<tt>&lt;student_number&gt;.pdf</tt><br>"
            "&nbsp;&nbsp;• <tt>config.json</tt> — grading scheme and export template<br>"
            "&nbsp;&nbsp;• <tt>students.csv</tt> — student roster"
        ))
        layout.addSpacing(8)

        form = QFormLayout()
        layout.addLayout(form)

        self._dir_edit = QLineEdit(self._project_dir)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self._dir_edit)
        dir_row.addWidget(browse_btn)
        form.addRow("Project directory:", dir_row)

        layout.addSpacing(12)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: red;")
        layout.addWidget(self._error_label)

        buttons = QDialogButtonBox()
        self._start_btn = buttons.addButton("Open Project", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select Project Directory",
                                                self._dir_edit.text())
        if path:
            self._dir_edit.setText(path)

    def _on_accept(self):
        project_dir = self._dir_edit.text().strip()

        if not os.path.isdir(project_dir):
            self._error_label.setText("Project directory does not exist.")
            return
        if not os.path.isdir(os.path.join(project_dir, "exams")):
            self._error_label.setText(
                "Missing 'exams/' sub-directory inside the project directory."
            )
            return
        if not os.path.isfile(os.path.join(project_dir, "config.json")):
            self._error_label.setText(
                "Missing 'config.json' inside the project directory."
            )
            return
        if not os.path.isfile(os.path.join(project_dir, "students.csv")):
            self._error_label.setText(
                "Missing 'students.csv' inside the project directory."
            )
            return

        data_store.save_session_config(project_dir)
        self._project_dir = project_dir
        self.accept()

    def project_dir(self) -> str:
        return self._project_dir
