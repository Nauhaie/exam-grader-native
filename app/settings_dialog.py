"""Unified settings dialog.

Combines:
 - Grading settings (max note, rounding, score total)
 - Export filename template
 - Grading scheme editor (exercises + subquestions)
 - Debug mode checkbox
"""
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import Exercise, GradingScheme, GradingSettings, Subquestion

_MIN_ROUNDING = 0.01   # smallest allowed rounding step in the dialog


class SettingsDialog(QDialog):
    """Unified settings dialog with tabs for Grading, Export/Debug, and Scheme."""

    def __init__(
        self,
        grading_settings: GradingSettings,
        grading_scheme: GradingScheme,
        exam_max_points: float,
        export_template: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self.setMinimumHeight(520)

        self._exam_max_points = exam_max_points

        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        tabs.addTab(self._build_grading_tab(grading_settings), "Grading")
        tabs.addTab(self._build_export_tab(grading_settings, export_template), "Export & Debug")
        tabs.addTab(self._build_scheme_tab(grading_scheme), "Grading Scheme")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── Tab builders ──────────────────────────────────────────────────────────

    def _build_grading_tab(self, settings: GradingSettings) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)

        info = QLabel(
            "<b>Grade formula</b><br>"
            "grade = round( (points / <i>score_total</i>) × <i>max_note</i>, "
            "<i>rounding</i> )"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addSpacing(8)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        layout.addLayout(form)

        self._max_note_spin = QDoubleSpinBox()
        self._max_note_spin.setRange(1.0, 1000.0)
        self._max_note_spin.setDecimals(1)
        self._max_note_spin.setSingleStep(1.0)
        self._max_note_spin.setValue(settings.max_note)
        self._max_note_spin.setToolTip("Maximum grade (e.g. 20 for French system)")
        form.addRow("Max note:", self._max_note_spin)

        self._rounding_spin = QDoubleSpinBox()
        self._rounding_spin.setRange(_MIN_ROUNDING, 10.0)
        self._rounding_spin.setDecimals(2)
        self._rounding_spin.setSingleStep(0.25)
        self._rounding_spin.setValue(settings.rounding)
        self._rounding_spin.setToolTip(
            "Round the final grade to the nearest multiple of this value.\n"
            "e.g. 0.5 → 12.5, 13.0 …   1.0 → 12, 13 …"
        )
        form.addRow("Rounding (multiple of):", self._rounding_spin)

        self._auto_cb = QCheckBox(
            f"Automatic (use exam total = {self._exam_max_points:g} pts)"
        )
        self._auto_cb.setToolTip(
            "When checked, score_total equals the sum of all subquestion max points."
        )
        self._auto_cb.setChecked(settings.score_total is None)
        self._auto_cb.toggled.connect(self._on_auto_toggled)
        form.addRow("Score total:", self._auto_cb)

        self._score_total_spin = QDoubleSpinBox()
        self._score_total_spin.setRange(0.01, 100_000.0)
        self._score_total_spin.setDecimals(2)
        self._score_total_spin.setSingleStep(1.0)
        self._score_total_spin.setValue(
            settings.score_total if settings.score_total is not None
            else max(self._exam_max_points, 1.0)
        )
        self._score_total_spin.setToolTip(
            "Denominator in the grade formula.  Set lower than the exam total\n"
            "to give a gentler curve."
        )
        self._score_total_spin.setEnabled(settings.score_total is not None)
        form.addRow("", self._score_total_spin)

        layout.addSpacing(8)

        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet("color: #444; font-style: italic;")
        layout.addWidget(self._preview)
        self._update_preview()

        self._max_note_spin.valueChanged.connect(self._update_preview)
        self._rounding_spin.valueChanged.connect(self._update_preview)
        self._score_total_spin.valueChanged.connect(self._update_preview)

        layout.addStretch()
        return w

    def _build_export_tab(self, settings: GradingSettings, template: str) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)

        form = QFormLayout()
        layout.addLayout(form)

        self._template_edit = QLineEdit(template)
        self._template_edit.setToolTip(
            "Filename template for exported annotated PDFs (without .pdf extension).\n"
            "Available placeholders: {student_number}, {last_name}, {first_name},\n"
            "and any extra columns from the students CSV."
        )
        form.addRow("Export filename template:", self._template_edit)

        layout.addSpacing(8)
        hint = QLabel(
            "Placeholders: <tt>{student_number}</tt>, <tt>{last_name}</tt>, "
            "<tt>{first_name}</tt> + any extra CSV columns."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555;")
        layout.addWidget(hint)

        layout.addSpacing(16)

        self._debug_cb = QCheckBox("Enable debug mode")
        self._debug_cb.setChecked(settings.debug_mode)
        self._debug_cb.setToolTip(
            "When enabled:\n"
            "  • Print detailed debug messages to the terminal during export\n"
            "  • Write a .log file next to each exported annotated PDF\n"
            "\n"
            "When disabled, no terminal output or log files are produced."
        )
        layout.addWidget(self._debug_cb)

        layout.addStretch()
        return w

    def _build_scheme_tab(self, scheme: GradingScheme) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)

        hint = QLabel(
            "Double-click a cell to edit.  "
            "Select a row and use the buttons below to add or remove items."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555;")
        layout.addWidget(hint)
        layout.addSpacing(4)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Name", "Max points"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setAlternatingRowColors(True)
        layout.addWidget(self._tree, stretch=1)

        for ex in scheme.exercises:
            self._add_exercise_item(ex.name, [
                (sq.name, sq.max_points) for sq in ex.subquestions
            ])

        self._tree.expandAll()

        btn_row = QHBoxLayout()
        layout.addLayout(btn_row)

        add_ex_btn = QPushButton("Add Exercise")
        add_ex_btn.setToolTip("Append a new exercise at the end")
        add_ex_btn.clicked.connect(self._on_add_exercise)
        btn_row.addWidget(add_ex_btn)

        add_sq_btn = QPushButton("Add Subquestion")
        add_sq_btn.setToolTip("Append a new subquestion to the selected exercise")
        add_sq_btn.clicked.connect(self._on_add_subquestion)
        btn_row.addWidget(add_sq_btn)

        del_btn = QPushButton("Delete")
        del_btn.setToolTip("Delete the selected exercise or subquestion")
        del_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(del_btn)

        btn_row.addStretch()

        up_btn = QPushButton("▲")
        up_btn.setFixedWidth(32)
        up_btn.setToolTip("Move selected item up")
        up_btn.clicked.connect(self._on_move_up)
        btn_row.addWidget(up_btn)

        down_btn = QPushButton("▼")
        down_btn.setFixedWidth(32)
        down_btn.setToolTip("Move selected item down")
        down_btn.clicked.connect(self._on_move_down)
        btn_row.addWidget(down_btn)

        return w

    # ── Grading tab helpers ───────────────────────────────────────────────────

    def _on_auto_toggled(self, checked: bool):
        self._score_total_spin.setEnabled(not checked)
        self._update_preview()

    def _update_preview(self):
        mn = self._max_note_spin.value()
        rd = max(_MIN_ROUNDING, self._rounding_spin.value())
        st = (self._exam_max_points if self._auto_cb.isChecked()
              else self._score_total_spin.value())
        if st <= 0:
            self._preview.setText("")
            return

        def fmt(pts):
            raw = (pts / st) * mn
            rounded = round(raw / rd) * rd
            return f"{rounded:g}"

        full = fmt(self._exam_max_points)
        half = fmt(self._exam_max_points / 2)
        self._preview.setText(
            f"Example: {self._exam_max_points:g} pts → <b>{full}</b> / {mn:g}  ·  "
            f"{self._exam_max_points / 2:g} pts → <b>{half}</b> / {mn:g}"
        )

    # ── Scheme tab helpers ────────────────────────────────────────────────────

    def _add_exercise_item(self, name: str,
                           subquestions: list[tuple[str, float]]) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self._tree)
        item.setText(0, name)
        item.setText(1, "")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setBackground(0, item.background(0))  # use default, just bold
        for sq_name, sq_pts in subquestions:
            self._add_subquestion_item(item, sq_name, sq_pts)
        return item

    def _add_subquestion_item(self, parent: QTreeWidgetItem,
                               name: str, pts: float) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent)
        item.setText(0, name)
        item.setText(1, str(pts))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        return item

    def _selected_exercise(self) -> Optional[QTreeWidgetItem]:
        """Return the exercise item for the current selection (or None)."""
        item = self._tree.currentItem()
        if item is None:
            return None
        if item.parent() is None:
            return item   # top-level = exercise
        return item.parent()   # child = subquestion → return its parent

    def _on_add_exercise(self):
        item = self._add_exercise_item("New Exercise", [])
        self._tree.setCurrentItem(item)
        self._tree.editItem(item, 0)

    def _on_add_subquestion(self):
        ex = self._selected_exercise()
        if ex is None:
            # No selection: add to the last exercise, or warn
            if self._tree.topLevelItemCount() == 0:
                QMessageBox.information(
                    self, "Add Subquestion",
                    "Add at least one exercise first."
                )
                return
            ex = self._tree.topLevelItem(self._tree.topLevelItemCount() - 1)
        item = self._add_subquestion_item(ex, "new", 1.0)
        ex.setExpanded(True)
        self._tree.setCurrentItem(item)
        self._tree.editItem(item, 0)

    def _on_delete(self):
        item = self._tree.currentItem()
        if item is None:
            return
        if item.parent() is None:
            # Deleting an exercise: warn if it has subquestions
            if item.childCount() > 0:
                reply = QMessageBox.question(
                    self, "Delete Exercise",
                    f"Delete exercise \"{item.text(0)}\" and all its subquestions?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            idx = self._tree.indexOfTopLevelItem(item)
            self._tree.takeTopLevelItem(idx)
        else:
            item.parent().removeChild(item)

    def _on_move_up(self):
        item = self._tree.currentItem()
        if item is None:
            return
        parent = item.parent()
        if parent is None:
            idx = self._tree.indexOfTopLevelItem(item)
            if idx > 0:
                self._tree.takeTopLevelItem(idx)
                self._tree.insertTopLevelItem(idx - 1, item)
                self._tree.setCurrentItem(item)
        else:
            idx = parent.indexOfChild(item)
            if idx > 0:
                parent.takeChild(idx)
                parent.insertChild(idx - 1, item)
                self._tree.setCurrentItem(item)

    def _on_move_down(self):
        item = self._tree.currentItem()
        if item is None:
            return
        parent = item.parent()
        if parent is None:
            idx = self._tree.indexOfTopLevelItem(item)
            if idx < self._tree.topLevelItemCount() - 1:
                self._tree.takeTopLevelItem(idx)
                self._tree.insertTopLevelItem(idx + 1, item)
                self._tree.setCurrentItem(item)
        else:
            idx = parent.indexOfChild(item)
            if idx < parent.childCount() - 1:
                parent.takeChild(idx)
                parent.insertChild(idx + 1, item)
                self._tree.setCurrentItem(item)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_settings(self) -> GradingSettings:
        return GradingSettings(
            max_note=self._max_note_spin.value(),
            rounding=self._rounding_spin.value(),
            score_total=(
                None if self._auto_cb.isChecked()
                else self._score_total_spin.value()
            ),
            debug_mode=self._debug_cb.isChecked(),
        )

    def get_export_template(self) -> str:
        return self._template_edit.text().strip() or "{student_number}_annotated"

    def get_grading_scheme(self) -> GradingScheme:
        exercises = []
        for i in range(self._tree.topLevelItemCount()):
            ex_item = self._tree.topLevelItem(i)
            ex_name = ex_item.text(0).strip() or f"Exercise {i + 1}"
            subquestions = []
            for j in range(ex_item.childCount()):
                sq_item = ex_item.child(j)
                sq_name = sq_item.text(0).strip() or f"q{i + 1}.{j + 1}"
                try:
                    sq_pts = float(sq_item.text(1))
                except ValueError:
                    sq_pts = 1.0
                subquestions.append(Subquestion(name=sq_name, max_points=sq_pts))
            exercises.append(Exercise(name=ex_name, subquestions=subquestions))
        return GradingScheme(exercises=exercises)
