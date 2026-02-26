"""Main entry point for Exam Grader native app."""
import csv
import os
import sys

import openpyxl
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
)

import data_store
import pdf_exporter
from grading_panel import GradingPanel
from models import Student
from pdf_viewer import PDFViewerPanel
from setup_dialog import SetupDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Exam Grader")
        self.resize(1400, 900)

        self._students = []
        self._grading_scheme = None
        self._exams_dir = ""
        self._grades = {}
        self._current_student = None

        self._setup_ui()
        self._load_session()

    def _setup_ui(self):
        file_menu = self.menuBar().addMenu("File")
        reconfigure_action = file_menu.addAction("Reconfigure…")
        reconfigure_action.triggered.connect(self._show_setup)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.triggered.connect(self.close)

        export_menu = self.menuBar().addMenu("Export")
        export_menu.addAction("Export Grades as CSV…").triggered.connect(self._export_csv)
        export_menu.addAction("Export Grades as XLSX…").triggered.connect(self._export_xlsx)
        export_menu.addAction("Export Annotated PDFs…").triggered.connect(self._export_annotated_pdfs)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # Left: PDF viewer only
        self._pdf_viewer = PDFViewerPanel()
        self._pdf_viewer.annotations_changed.connect(self._on_annotations_changed)
        self._pdf_viewer.jump_requested.connect(self._on_jump_requested)
        self._pdf_viewer.student_prev_requested.connect(self._select_prev_student)
        self._pdf_viewer.student_next_requested.connect(self._select_next_student)
        splitter.addWidget(self._pdf_viewer)

        # Right: grading spreadsheet
        self._grading_panel = GradingPanel()
        self._grading_panel.grade_changed.connect(self._on_grade_changed)
        self._grading_panel.student_selected.connect(self._on_student_selected)
        splitter.addWidget(self._grading_panel)

        splitter.setSizes([600, 800])

    def _load_session(self):
        config = data_store.load_session_config()
        if config:
            exams_dir = config.get("exams_dir", "")
            students_csv = config.get("students_csv", "")
            grading_scheme_path = config.get("grading_scheme", "")
            if (os.path.isdir(exams_dir)
                    and os.path.isfile(students_csv)
                    and os.path.isfile(grading_scheme_path)):
                try:
                    self._students = data_store.load_students(students_csv)
                    self._grading_scheme = data_store.load_grading_scheme(grading_scheme_path)
                    self._exams_dir = exams_dir
                    self._grades = data_store.load_grades()
                    self._apply_session()
                    return
                except Exception as exc:
                    QMessageBox.warning(
                        self, "Load Error",
                        f"Could not restore previous session:\n{exc}\n\nPlease reconfigure."
                    )
        self._show_setup()

    def _show_setup(self):
        dlg = SetupDialog(self)
        if dlg.exec():
            config = data_store.load_session_config()
            self._exams_dir = config["exams_dir"]
            self._students = data_store.load_students(config["students_csv"])
            self._grading_scheme = data_store.load_grading_scheme(config["grading_scheme"])
            self._grades = data_store.load_grades()
            self._apply_session()

    def _apply_session(self):
        self._grading_panel.set_session(self._students, self._grading_scheme, self._grades)
        if self._students:
            self._select_student(self._students[0])

    def _select_student(self, student: Student):
        if (self._current_student
                and student.student_number == self._current_student.student_number):
            return
        self._current_student = student
        self._grading_panel.set_current_student(student)
        pdf_path = os.path.join(self._exams_dir, f"{student.student_number}.pdf")
        annotations = data_store.load_annotations(student.student_number)
        self._pdf_viewer.load_pdf(pdf_path, annotations)

    def _on_student_selected(self, student):
        if student is None:
            return
        self._select_student(student)

    def _on_annotations_changed(self):
        if self._current_student:
            data_store.save_annotations(
                self._current_student.student_number,
                self._pdf_viewer.get_annotations(),
            )

    def _on_grade_changed(self, student_number: str, subquestion_name: str, points: float):
        if student_number not in self._grades:
            self._grades[student_number] = {}
        self._grades[student_number][subquestion_name] = points
        data_store.save_grades(self._grades)

    def _export_csv(self):
        if not self._grading_scheme or not self._students:
            QMessageBox.warning(self, "Export", "No session configured.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Grades as CSV", "grades.csv", "CSV files (*.csv)"
        )
        if not path:
            return
        subquestions = [sq for ex in self._grading_scheme.exercises for sq in ex.subquestions]
        fieldnames = ["student_number", "last_name", "first_name"] + [sq.name for sq in subquestions]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for student in self._students:
                sg = self._grades.get(student.student_number, {})
                row = {
                    "student_number": student.student_number,
                    "last_name": student.last_name,
                    "first_name": student.first_name,
                }
                for sq in subquestions:
                    row[sq.name] = sg.get(sq.name, "")
                writer.writerow(row)
        QMessageBox.information(self, "Export", f"Grades exported to:\n{path}")

    def _export_xlsx(self):
        if not self._grading_scheme or not self._students:
            QMessageBox.warning(self, "Export", "No session configured.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Grades as XLSX", "grades.xlsx", "Excel files (*.xlsx)"
        )
        if not path:
            return
        subquestions = [sq for ex in self._grading_scheme.exercises for sq in ex.subquestions]
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Grades"
        ws.append(["student_number", "last_name", "first_name"] + [sq.name for sq in subquestions])
        for student in self._students:
            sg = self._grades.get(student.student_number, {})
            ws.append(
                [student.student_number, student.last_name, student.first_name]
                + [sg.get(sq.name, "") for sq in subquestions]
            )
        wb.save(path)
        QMessageBox.information(self, "Export", f"Grades exported to:\n{path}")

    def _export_annotated_pdfs(self):
        if not self._students:
            QMessageBox.warning(self, "Export", "No session configured.")
            return
        output_dir = QFileDialog.getExistingDirectory(
            self, "Select Output Directory for Annotated PDFs"
        )
        if not output_dir:
            return

        # Ask for a filename template
        from PySide6.QtWidgets import QInputDialog
        extra_keys = []
        for s in self._students:
            for k in s.extra_fields:
                if k not in extra_keys:
                    extra_keys.append(k)
        hint = "  Available: {student_number}, {last_name}, {first_name}"
        if extra_keys:
            hint += ", " + ", ".join(f"{{{k}}}" for k in extra_keys)
        template, ok = QInputDialog.getText(
            self,
            "Filename Template",
            f"Output filename template (without .pdf):\n{hint}",
            text="{student_number}_annotated",
        )
        if not ok:
            return
        template = template.strip() or "{student_number}_annotated"

        # Flush current student's annotations so the export is up-to-date
        if self._current_student:
            data_store.save_annotations(
                self._current_student.student_number,
                self._pdf_viewer.get_annotations(),
            )

        from PySide6.QtWidgets import QProgressDialog
        progress = QProgressDialog(
            "Exporting annotated PDFs…", "Cancel", 0, len(self._students), self
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()

        exported = skipped = 0
        for i, student in enumerate(self._students):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            QApplication.processEvents()
            src = os.path.join(self._exams_dir, f"{student.student_number}.pdf")
            if not os.path.isfile(src):
                skipped += 1
                continue
            anns = data_store.load_annotations(student.student_number)

            fields = dict(student.extra_fields)
            fields.update(
                student_number=student.student_number,
                last_name=student.last_name,
                first_name=student.first_name,
            )
            try:
                stem = template.format_map(fields)
            except (KeyError, ValueError):
                stem = f"{student.student_number}_annotated"
            dst = os.path.join(output_dir, f"{stem}.pdf")

            try:
                pdf_exporter.bake_annotations(src, anns, dst)
                exported += 1
            except Exception as exc:
                QMessageBox.warning(
                    self, "Export Error",
                    f"Failed to export {student.student_number}:\n{exc}"
                )

        progress.setValue(len(self._students))
        msg = f"Exported {exported} annotated PDF(s) to:\n{output_dir}"
        if skipped:
            msg += f"\n({skipped} student(s) skipped — PDF not found)"
        QMessageBox.information(self, "Export", msg)

    def _on_jump_requested(self):
        """'P' key: jump to the grading row for the current student."""
        if self._current_student:
            self._grading_panel.focus_student_cell(
                self._current_student.student_number
            )

    def _select_prev_student(self):
        """Shift+Alt+Left: go to previous student."""
        if not self._students or not self._current_student:
            return
        idx = next(
            (i for i, s in enumerate(self._students)
             if s.student_number == self._current_student.student_number), -1
        )
        if idx > 0:
            self._select_student(self._students[idx - 1])

    def _select_next_student(self):
        """Shift+Alt+Right: go to next student."""
        if not self._students or not self._current_student:
            return
        idx = next(
            (i for i, s in enumerate(self._students)
             if s.student_number == self._current_student.student_number), -1
        )
        if 0 <= idx < len(self._students) - 1:
            self._select_student(self._students[idx + 1])


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Exam Grader")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
