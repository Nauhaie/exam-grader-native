"""Dialog for editing grading settings (max note, rounding, score total)."""
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from models import GradingSettings

_MIN_ROUNDING = 0.01   # smallest allowed rounding step in the dialog


class GradingSettingsDialog(QDialog):
    """Let the user configure how raw points are converted to a final grade.

    Formula:  grade = round_to_multiple(points / score_total * max_note, rounding)
    """

    def __init__(self, settings: GradingSettings, exam_max_points: float,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Grading Settings")
        self.setMinimumWidth(380)

        self._exam_max_points = exam_max_points

        layout = QVBoxLayout(self)

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

        # ── Max note ─────────────────────────────────────────────────────────
        self._max_note_spin = QDoubleSpinBox()
        self._max_note_spin.setRange(1.0, 1000.0)
        self._max_note_spin.setDecimals(1)
        self._max_note_spin.setSingleStep(1.0)
        self._max_note_spin.setValue(settings.max_note)
        self._max_note_spin.setToolTip("Maximum grade (e.g. 20 for French system)")
        form.addRow("Max note:", self._max_note_spin)

        # ── Rounding ─────────────────────────────────────────────────────────
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

        # ── Score total ───────────────────────────────────────────────────────
        self._auto_cb = QCheckBox(
            f"Automatic (use exam total = {exam_max_points:g} pts)"
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
            else max(exam_max_points, 1.0)
        )
        self._score_total_spin.setToolTip(
            "Denominator in the grade formula.  Set lower than the exam total\n"
            "to give a gentler curve."
        )
        self._score_total_spin.setEnabled(settings.score_total is not None)
        form.addRow("", self._score_total_spin)

        layout.addSpacing(8)

        # ── Preview label ─────────────────────────────────────────────────────
        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet("color: #444; font-style: italic;")
        layout.addWidget(self._preview)
        self._update_preview()
        self._max_note_spin.valueChanged.connect(self._update_preview)
        self._rounding_spin.valueChanged.connect(self._update_preview)
        self._score_total_spin.valueChanged.connect(self._update_preview)

        layout.addSpacing(8)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── Internal ──────────────────────────────────────────────────────────────

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
        # Show example: full marks and half marks
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

    # ── Public API ────────────────────────────────────────────────────────────

    def get_settings(self) -> GradingSettings:
        return GradingSettings(
            max_note=self._max_note_spin.value(),
            rounding=self._rounding_spin.value(),
            score_total=(
                None if self._auto_cb.isChecked()
                else self._score_total_spin.value()
            ),
        )
