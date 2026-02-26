# Exam Grader

A desktop application for grading scanned exams: view PDFs, add annotations,
enter scores and export fully annotated PDFs.

---

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

```bash
pip install -r requirements.txt
```

---

## Running

```bash
cd app
python main.py
```

---

## First-time setup

On first launch (or via **File → Reconfigure…**) you will be asked for:

| Field | Description |
|---|---|
| **Exams directory** | Folder containing one PDF per student, named `<student_number>.pdf` |
| **Students CSV** | CSV with at minimum the columns `student_number`, `last_name`, `first_name`. Any additional columns (e.g. `participantID`, `group`, remarks…) are stored and can be shown/hidden in the grading view. |
| **Grading scheme JSON** | Describes exercises and sub-questions (see `sample_data/grading_scheme.json`). |

---

## Grading workflow

1. Select a student from the grading table (right panel) or use **Shift+Alt+←/→**.
2. Use the annotation tools in the PDF toolbar (left panel) to mark the exam.
3. Enter scores directly in the grading table cells (double-click or just type).
4. Press **P** to jump focus back to the current student's grading row.
5. Everything is auto-saved continuously.

---

## Annotation tools

| Button | Key | Tool |
|--------|-----|------|
| ✓ | **V** | Checkmark (green) |
| ✗ | **X** | Cross (red) |
| T | **T** | Text note (click to place, **Enter** = newline, **Ctrl+Enter** = confirm, **Esc** = cancel; double-click existing note to edit) |
| ╱ | **L** | Line (red) |
| → | **A** | Arrow (red) |
| ○ | **O** | Circle (red, grab circumference to move/resize) |
| ~ | **N** | Approx/tilde (orange, "approximately correct") |
| ⌫ | **E** | Eraser (click annotation to delete) |

For **line / arrow / circle**: click once to set the start point, click again to finish.  
Press **Esc** to cancel a shape in progress.

To **move or resize** an existing annotation: select no tool (press the active tool button again to deselect), then drag the annotation.

---

## Keyboard shortcuts

### Navigation

| Shortcut | Action |
|----------|--------|
| **Alt + →** | Next page |
| **Alt + ←** | Previous page |
| **→** / **←** | Next / previous page **(only when the PDF fits the view without scrollbars)** |
| **Shift + Alt + →** | Next student |
| **Shift + Alt + ←** | Previous student |
| **P** | Jump grading focus to current student |
| **Ctrl + scroll** | Zoom in / out |
| Pinch gesture (macOS) | Zoom in / out |

### View

| Shortcut | Action |
|----------|--------|
| **Cmd (macOS) / Ctrl (Win/Linux) + drag** | Pan / scroll the PDF by dragging |

### Annotation tools

| Key | Tool |
|-----|------|
| **V** | Checkmark |
| **X** | Cross |
| **T** | Text |
| **L** | Line |
| **A** | Arrow |
| **O** | Circle |
| **N** | Approx/tilde (~) |
| **E** | Eraser |
| **Esc** | Cancel in-progress shape / deselect tool |

*(Pressing a tool key again while that tool is active deselects it.)*

---

## Extra CSV fields

The students CSV may contain any additional columns beyond the three required
ones.  In the grading panel click **Extra fields** to toggle their display as
read-only columns.  Extra fields are also searchable from the filter box.

---

## Exporting

### Annotated PDFs

**Export → Export Annotated PDFs…**

You will be prompted for an output directory and a **filename template**.
The template may use any CSV field name in curly braces, e.g.:

```
Interro1_{participantID}_annotated
Exam_{last_name}_{first_name}
{student_number}_graded
```

Available placeholders: `{student_number}`, `{last_name}`, `{first_name}`, and
any extra column from your CSV.

### Grades

- **Export → Export Grades as CSV…**
- **Export → Export Grades as XLSX…**

---

## Packaging as a standalone app

Use the included `package-app.sh` script.  It creates a self-contained
application bundle in `dist/` using PyInstaller.

```bash
# Install packaging tool (once)
pip install pyinstaller

# Build
bash package-app.sh
```

| Platform | Output |
|----------|--------|
| macOS | `dist/ExamGrader.app` (drag to Applications) |
| Windows | `dist/ExamGrader/ExamGrader.exe` |
| Linux | `dist/ExamGrader/ExamGrader` |

> **Note:** The `data/` folder (session config, grades, annotations) is always
> stored next to the application's source, not inside the bundle.

---

## Project structure

```
app/
  main.py              – entry point, main window
  pdf_viewer.py        – PDF display + annotation UI
  annotation_overlay.py – Qt drawing of annotation markers
  pdf_exporter.py      – bake annotations into PDFs for export
  grading_panel.py     – grade-entry spreadsheet
  data_store.py        – load/save sessions, students, grades, annotations
  models.py            – data classes
  setup_dialog.py      – first-run configuration dialog
sample_data/           – example CSV, JSON and exam PDFs
data/                  – runtime data (auto-created, not in version control)
requirements.txt
package-app.sh
```
