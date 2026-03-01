"""Main entry point for Exam Grader native app."""
import csv
import os
import subprocess
import sys
from typing import List

import openpyxl
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QAction, QCursor
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


class _SplitterCursorFilter(QObject):
    """macOS workaround: NSTrackingArea cursor rects become stale after
    full-screen transitions, causing spurious Leave events that reset the
    QSplitter-handle cursor back to the arrow pointer even while the mouse
    is still hovering over the separator.

    Using QApplication.setOverrideCursor() instead of handle.setCursor()
    bypasses the NSTrackingArea mechanism entirely, so the split cursor
    survives full-screen transitions in both directions.

    This filter is installed on the handle widget and:
      • pushes SplitHCursor as an application override on Enter / HoverEnter /
        HoverMove / MouseMove when the cursor is geometrically inside the handle;
      • suppresses spurious Leave / HoverLeave events (mouse still inside handle)
        that macOS fires after a full-screen transition;
      • pops the override when the mouse genuinely leaves the handle.
    """

    def __init__(self, handle: QWidget, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._handle = handle
        self._override_active = False
        handle.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        handle.setMouseTracking(True)
        handle.installEventFilter(self)

    # ------------------------------------------------------------------
    # Override-cursor helpers
    # ------------------------------------------------------------------

    def _set_split_cursor(self) -> None:
        """Push SplitHCursor as the application override (idempotent)."""
        if not self._override_active:
            QApplication.setOverrideCursor(Qt.CursorShape.SplitHCursor)
            self._override_active = True

    def _clear_split_cursor(self) -> None:
        """Pop the application override cursor (idempotent)."""
        if self._override_active:
            QApplication.restoreOverrideCursor()
            self._override_active = False

    # ------------------------------------------------------------------
    # Event filter
    # ------------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is not self._handle:
            return super().eventFilter(watched, event)

        etype = event.type()

        if etype in (
            QEvent.Type.Enter,
            QEvent.Type.HoverEnter,
            QEvent.Type.HoverMove,
            QEvent.Type.MouseMove,
        ):
            if self._cursor_over_handle():
                self._set_split_cursor()
            return False

        if etype in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            if self._cursor_over_handle():
                # Spurious Leave – mouse is still inside the handle;
                # suppress the event and keep the split cursor active.
                self._set_split_cursor()
                return True
            self._clear_split_cursor()
            return False

        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------
    # Public API for use after window-state transitions
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset override-cursor state and resync after a window transition.

        Clears any stale override first, rebuilds the platform tracking
        areas, then re-applies the override if the pointer is already
        over the handle.  Works for both windowed→full-screen and
        full-screen→windowed transitions.
        """
        self._clear_split_cursor()
        # Toggling mouse-tracking prompts Qt to tear down and recreate the
        # platform tracking areas, repairing stale NSTrackingArea rects.
        self._handle.setMouseTracking(False)
        self._handle.setMouseTracking(True)
        self._handle.update()
        # Re-apply the override immediately if the pointer is already there.
        if self._cursor_over_handle():
            self._set_split_cursor()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cursor_over_handle(self) -> bool:
        """Return True if the system cursor is inside the handle's screen rect."""
        return QRect(
            self._handle.mapToGlobal(QPoint(0, 0)),
            self._handle.size(),
        ).contains(QCursor.pos())


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
        self._splitter = splitter

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

        # macOS: install cursor filter to survive full-screen transitions.
        if sys.platform == "darwin":
            self._splitter_cursor_filter = _SplitterCursorFilter(
                splitter.handle(1), self
            )

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if (sys.platform == "darwin"
                and event.type() == QEvent.Type.WindowStateChange):
            # After a full-screen transition the NSTrackingArea cursor rects
            # become stale; reschedule a resync once the animation settles.
            QTimer.singleShot(300, self._resync_cursors)

    def _resync_cursors(self) -> None:
        """Reset cursor tracking state after a window-state transition."""
        if hasattr(self, "_splitter_cursor_filter"):
            self._splitter_cursor_filter.reset()

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

    def _compute_student_grade(self, sg: dict, subquestions) -> tuple:
        """Return (total_points, final_grade) for a student's scores dict."""
        gs = self._grading_settings
        scheme_total = self._grading_scheme.max_total()
        score_total = gs.score_total if gs.score_total is not None else scheme_total
        pts = sum(sg.get(sq.name, 0) or 0 for sq in subquestions)
        if score_total <= 0:
            return pts, 0.0
        # Round to nearest multiple of gs.rounding (same as GradingPanel)
        step = max(0.001, gs.rounding)
        grade = round((pts / score_total) * gs.max_note / step) * step
        return pts, grade

    def _extra_field_names(self) -> List[str]:
        """Return the ordered union of extra field names across all students."""
        names: List[str] = []
        seen: set = set()
        for s in self._students:
            for k in s.extra_fields:
                if k not in seen:
                    seen.add(k)
                    names.append(k)
        return names

    def _export_csv(self):
        if not self._grading_scheme or not self._students:
            QMessageBox.warning(self, "Export", "No project open.")
            return
        path = os.path.join(data_store.EXPORT_DIR, "grades.csv")
        subquestions = [sq for ex in self._grading_scheme.exercises for sq in ex.subquestions]
        extra_names = self._extra_field_names()
        fieldnames = (["student_number", "last_name", "first_name"]
                      + extra_names
                      + [sq.name for sq in subquestions]
                      + ["total", "grade"])
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
                for name in extra_names:
                    row[name] = student.extra_fields.get(name, "")
                for sq in subquestions:
                    row[sq.name] = sg.get(sq.name, "")
                pts, grade = self._compute_student_grade(sg, subquestions)
                row["total"] = pts
                row["grade"] = grade
                writer.writerow(row)
        dlg = QMessageBox(QMessageBox.Icon.Information, "Export",
                          f"Grades exported to:\n{path}", parent=self)
        open_btn = dlg.addButton("Open File", QMessageBox.ButtonRole.ActionRole)
        dlg.addButton(QMessageBox.StandardButton.Ok)
        dlg.exec()
        if dlg.clickedButton() is open_btn:
            _open_path(path)

    def _export_xlsx(self):
        if not self._grading_scheme or not self._students:
            QMessageBox.warning(self, "Export", "No project open.")
            return
        path = os.path.join(data_store.EXPORT_DIR, "grades.xlsx")
        subquestions = [sq for ex in self._grading_scheme.exercises for sq in ex.subquestions]
        extra_names = self._extra_field_names()
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Grades"
        ws.append(["student_number", "last_name", "first_name"]
                  + extra_names
                  + [sq.name for sq in subquestions]
                  + ["total", "grade"])
        for student in self._students:
            sg = self._grades.get(student.student_number, {})
            pts, grade = self._compute_student_grade(sg, subquestions)
            ws.append(
                [student.student_number, student.last_name, student.first_name]
                + [student.extra_fields.get(name, "") for name in extra_names]
                + [sg.get(sq.name, "") for sq in subquestions]
                + [pts, grade]
            )
        wb.save(path)
        dlg = QMessageBox(QMessageBox.Icon.Information, "Export",
                          f"Grades exported to:\n{path}", parent=self)
        open_btn = dlg.addButton("Open File", QMessageBox.ButtonRole.ActionRole)
        dlg.addButton(QMessageBox.StandardButton.Ok)
        dlg.exec()
        if dlg.clickedButton() is open_btn:
            _open_path(path)

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
        ok_btn.setDefault(True)
        open_btn.clicked.connect(lambda: _open_path(output_dir))
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


def _open_path(path: str) -> None:
    """Open *path* with the platform's default handler (file or directory)."""
    if not os.path.exists(path):
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
