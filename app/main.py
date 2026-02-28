"""Main entry point for Exam Grader native app."""
import csv
import os
import subprocess
import sys
from typing import List

import openpyxl
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import data_store
import pdf_exporter
from grading_panel import GradingPanel
from models import GradingSettings, Student
from pdf_viewer import PDFViewerPanel
from settings_dialog import SettingsDialog
from setup_dialog import SetupDialog


class _EmptyDefault(dict):
    """dict subclass that returns 'EMPTY' for missing keys."""
    def __missing__(self, key):
        return "EMPTY"


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
        self._export_template = "{student_number}_annotated"
        self._project_config: dict = {}
        self._grading_settings: GradingSettings = GradingSettings()
        self._preset_annotations: list = []

        self._setup_ui()
        self._load_session()

    def _setup_ui(self):
        file_menu = self.menuBar().addMenu("File")
        reconfigure_action = file_menu.addAction("Open Project…")
        reconfigure_action.triggered.connect(self._show_setup)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.triggered.connect(self.close)

        project_menu = self.menuBar().addMenu("Project")
        settings_action = project_menu.addAction("Settings…")
        settings_action.setMenuRole(QAction.MenuRole.NoRole)
        settings_action.triggered.connect(self._show_settings)
        project_menu.addSeparator()
        project_menu.addAction("Export Grades as CSV").triggered.connect(self._export_csv)
        project_menu.addAction("Export Grades as XLSX").triggered.connect(self._export_xlsx)
        project_menu.addAction("Export Annotated PDFs").triggered.connect(self._export_annotated_pdfs)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # Left: PDF viewer only
        self._pdf_viewer = PDFViewerPanel()
        self._pdf_viewer.annotations_changed.connect(self._on_annotations_changed)
        self._pdf_viewer.jump_requested.connect(self._on_jump_requested)
        self._pdf_viewer.student_prev_requested.connect(self._select_prev_student)
        self._pdf_viewer.student_next_requested.connect(self._select_next_student)
        self._pdf_viewer.open_settings_presets_requested.connect(
            lambda: self._show_settings(initial_tab=3)
        )
        splitter.addWidget(self._pdf_viewer)

        # Right: grading spreadsheet
        self._grading_panel = GradingPanel()
        self._grading_panel.grade_changed.connect(self._on_grade_changed)
        self._grading_panel.student_selected.connect(self._on_student_selected)
        splitter.addWidget(self._grading_panel)

        splitter.setSizes([600, 800])

    def _load_session(self):
        data_store.dbg("Loading previous session…")
        config = data_store.load_session_config()
        if config:
            project_dir = config.get("project_dir", "")
            if os.path.isdir(project_dir):
                try:
                    self._apply_project(project_dir)
                    return
                except Exception as exc:
                    QMessageBox.warning(
                        self, "Load Error",
                        f"Could not restore previous session:\n{exc}\n\nPlease open a project."
                    )
        data_store.dbg("No previous session found, showing setup dialog")
        self._show_setup()

    def _show_setup(self):
        dlg = SetupDialog(self)
        if dlg.exec():
            self._apply_project(dlg.project_dir())

    def _apply_project(self, project_dir: str):
        data_store.dbg(f"Applying project: {project_dir}")
        data_store.set_project_dir(project_dir)
        self._project_config = data_store.load_project_config(project_dir)
        self._grading_scheme = data_store.load_grading_scheme_from_config(self._project_config)
        self._grading_settings = data_store.load_grading_settings_from_config(self._project_config)
        data_store.set_debug(self._grading_settings.debug_mode)
        self._export_template = data_store.get_export_filename_template(self._project_config)
        self._preset_annotations = data_store.load_preset_annotations(self._project_config)
        self._exams_dir = os.path.join(project_dir, "exams")
        self._students = data_store.load_students(os.path.join(project_dir, "students.csv"))
        self._grades = data_store.load_grades()
        data_store.ensure_data_dirs()
        self._grading_panel.set_session(self._students, self._grading_scheme, self._grades)
        self._grading_panel.set_grading_settings(self._grading_settings)
        self._pdf_viewer.set_hi_dpr(self._grading_settings.hi_dpr)
        self._pdf_viewer.set_preset_annotations(self._preset_annotations)
        data_store.dbg(f"Project applied successfully: {len(self._students)} student(s)")
        if self._students:
            self._select_student(self._students[0])

    def _show_settings(self, initial_tab: int = 0):
        if not self._grading_scheme:
            QMessageBox.warning(self, "Settings", "Open a project first.")
            return
        exam_pts = self._grading_panel.exam_max_points()
        # Collect the union of all extra field names across all students
        extra_names: List[str] = []
        seen: set = set()
        for s in self._students:
            for k in s.extra_fields:
                if k not in seen:
                    seen.add(k)
                    extra_names.append(k)
        dlg = SettingsDialog(
            self._grading_settings,
            self._grading_scheme,
            exam_pts,
            self._export_template,
            self._preset_annotations,
            self,
            extra_field_names=extra_names,
        )
        if initial_tab:
            dlg.select_tab(initial_tab)
        if dlg.exec():
            self._grading_settings = dlg.get_settings()
            data_store.set_debug(self._grading_settings.debug_mode)
            data_store.dbg("Settings updated from dialog")
            self._export_template = dlg.get_export_template()
            new_scheme = dlg.get_grading_scheme()
            self._grading_scheme = new_scheme
            self._preset_annotations = dlg.get_preset_annotations()
            self._grading_panel.set_grading_settings(self._grading_settings)
            self._pdf_viewer.set_hi_dpr(self._grading_settings.hi_dpr)
            self._grading_panel.set_session(
                self._students, self._grading_scheme, self._grades
            )
            self._pdf_viewer.set_preset_annotations(self._preset_annotations)
            # Persist to config.json
            project_dir = data_store.get_project_dir()
            if project_dir:
                data_store.save_grading_settings_to_config(
                    self._project_config, self._grading_settings
                )
                data_store.save_export_template_to_config(
                    self._project_config, self._export_template
                )
                data_store.save_grading_scheme_to_config(
                    self._project_config, self._grading_scheme
                )
                data_store.save_preset_annotations_to_config(
                    self._project_config, self._preset_annotations
                )
                data_store.save_project_config(project_dir, self._project_config)

    def _select_student(self, student: Student):
        if (self._current_student
                and student.student_number == self._current_student.student_number):
            return
        data_store.dbg(f"Selecting student: {student.display_name()}")
        self._current_student = student
        self._grading_panel.set_current_student(student)
        pdf_path = os.path.join(self._exams_dir, f"{student.student_number}.pdf")
        annotations = data_store.load_annotations(student.student_number)
        data_store.dbg(f"Loading PDF: {pdf_path}")
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
            QMessageBox.warning(self, "Export", "No project open.")
            return
        path = os.path.join(data_store.EXPORT_DIR, "grades.csv")
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
        dlg = QMessageBox(QMessageBox.Icon.Information, "Export",
                          f"Grades exported to:\n{path}", parent=self)
        open_btn = dlg.addButton("Open File", QMessageBox.ButtonRole.ActionRole)
        dlg.addButton(QMessageBox.StandardButton.Ok)
        dlg.exec()
        if dlg.clickedButton() is open_btn:
            _open_file(path)

    def _export_xlsx(self):
        if not self._grading_scheme or not self._students:
            QMessageBox.warning(self, "Export", "No project open.")
            return
        path = os.path.join(data_store.EXPORT_DIR, "grades.xlsx")
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
        dlg = QMessageBox(QMessageBox.Icon.Information, "Export",
                          f"Grades exported to:\n{path}", parent=self)
        open_btn = dlg.addButton("Open File", QMessageBox.ButtonRole.ActionRole)
        dlg.addButton(QMessageBox.StandardButton.Ok)
        dlg.exec()
        if dlg.clickedButton() is open_btn:
            _open_file(path)

    def _export_annotated_pdfs(self):
        if not self._students:
            QMessageBox.warning(self, "Export", "No project open.")
            return

        # Flush current student's annotations so the export is up-to-date
        if self._current_student:
            data_store.save_annotations(
                self._current_student.student_number,
                self._pdf_viewer.get_annotations(),
            )

        output_dir = data_store.ANNOTATED_EXPORT_DIR
        template = self._export_template
        debug = self._grading_settings.debug_mode

        os.makedirs(output_dir, exist_ok=True)
        if debug:
            os.makedirs(data_store.ANNOTATED_LOGS_DIR, exist_ok=True)

        if debug:
            print(f"[Export] Starting annotated PDF export to: {output_dir}")
            print(f"[Export] {len(self._students)} student(s) to process")

        # Single dialog: progress bar → completion message
        dlg = QDialog(self)
        dlg.setWindowTitle("Export Annotated PDFs")
        dlg.setMinimumWidth(420)
        dlg_layout = QVBoxLayout(dlg)
        status_label = QLabel("Exporting annotated PDFs…")
        dlg_layout.addWidget(status_label)
        progress_bar = QProgressBar()
        progress_bar.setRange(0, len(self._students))
        progress_bar.setValue(0)
        dlg_layout.addWidget(progress_bar)
        btn_box = QDialogButtonBox()
        cancel_btn = btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        dlg_layout.addWidget(btn_box)
        dlg.setModal(True)
        dlg.show()

        cancelled = False

        def on_cancel():
            nonlocal cancelled
            cancelled = True

        cancel_btn.clicked.connect(on_cancel)

        exported = skipped = 0
        for i, student in enumerate(self._students):
            if cancelled:
                if debug:
                    print("[Export] Cancelled by user.")
                break
            progress_bar.setValue(i)
            status_label.setText(
                f"Exporting annotated PDFs… ({i + 1}/{len(self._students)})"
            )
            QApplication.processEvents()
            src = os.path.join(self._exams_dir, f"{student.student_number}.pdf")
            if not os.path.isfile(src):
                if debug:
                    print(f"[Export] SKIP {student.student_number}: PDF not found at {src}")
                skipped += 1
                continue
            anns = data_store.load_annotations(student.student_number)

            fields = {k: (v if v else "EMPTY") for k, v in student.extra_fields.items()}
            fields.update(
                student_number=student.student_number or "EMPTY",
                last_name=student.last_name or "EMPTY",
                first_name=student.first_name or "EMPTY",
            )
            try:
                stem = template.format_map(_EmptyDefault(fields))
            except ValueError:
                stem = f"{student.student_number}_annotated"
            dst = os.path.join(output_dir, f"{stem}.pdf")
            log_path = os.path.join(data_store.ANNOTATED_LOGS_DIR, f"{stem}.log") if debug else None

            if debug:
                print(f"[Export] [{i+1}/{len(self._students)}] {student.student_number} → {dst}")
                print(f"[Export]   log file → {log_path}")

            try:
                student_grades = self._grades.get(student.student_number, {})
                pdf_exporter.bake_annotations(src, anns, dst, log_path=log_path,
                                              debug=debug,
                                              student=student,
                                              grades=student_grades,
                                              scheme=self._grading_scheme,
                                              settings=self._grading_settings)
                if debug and log_path and os.path.isfile(log_path):
                    print(f"[Export]   log written OK ({os.path.getsize(log_path)} bytes)")
                elif debug and log_path:
                    print(f"[Export]   WARNING: log file was NOT created at {log_path}")
                exported += 1
            except Exception as exc:
                if debug:
                    print(f"[Export]   ERROR: {exc}")
                QMessageBox.warning(
                    self, "Export Error",
                    f"Failed to export {student.student_number}:\n{exc}"
                )

        if debug:
            print(f"[Export] Done. exported={exported}, skipped={skipped}")

        # Transition the same dialog to show the completion message
        progress_bar.setValue(len(self._students))
        msg = f"Exported {exported} annotated PDF(s) to:\n{output_dir}"
        if skipped:
            msg += f"\n({skipped} student(s) skipped — PDF not found)"
        status_label.setText(msg)
        progress_bar.hide()

        # Replace Cancel with Open Folder + OK
        btn_box.clear()
        open_btn = btn_box.addButton("Open Folder", QDialogButtonBox.ButtonRole.ActionRole)
        ok_btn = btn_box.addButton(QDialogButtonBox.StandardButton.Ok)
        open_btn.clicked.connect(lambda: _open_folder(output_dir))
        ok_btn.clicked.connect(dlg.accept)
        dlg.exec()

    def _on_jump_requested(self):
        """'P' key: jump to the grading row for the current student."""
        if self._current_student:
            self._grading_panel.focus_student_cell(
                self._current_student.student_number
            )

    def _select_prev_student(self):
        """Shift+Alt+Left: go to previous visible (filtered) student."""
        if not self._students or not self._current_student:
            return
        visible = self._grading_panel.filtered_students()
        idx = next(
            (i for i, s in enumerate(visible)
             if s.student_number == self._current_student.student_number), -1
        )
        if idx > 0:
            self._select_student(visible[idx - 1])

    def _select_next_student(self):
        """Shift+Alt+Right: go to next visible (filtered) student."""
        if not self._students or not self._current_student:
            return
        visible = self._grading_panel.filtered_students()
        idx = next(
            (i for i, s in enumerate(visible)
             if s.student_number == self._current_student.student_number), -1
        )
        if 0 <= idx < len(visible) - 1:
            self._select_student(visible[idx + 1])


def _open_folder(path: str) -> None:
    """Open *path* in the platform's file manager (Finder, Explorer, etc.)."""
    if not os.path.isdir(path):
        return
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def _open_file(path: str) -> None:
    """Open *path* with the platform's default application."""
    if not os.path.isfile(path):
        return
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Exam Grader")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
