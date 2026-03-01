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

## Project directory structure

The app works with a **project directory** that you provide once via
**File → Open Project…** (also shown on first launch).  The directory must
contain:

```
my_project/
  exams/          ← one PDF per student, named <student_number>.pdf
  config.json     ← grading scheme + export filename template
  students.csv    ← student roster
```

The app will automatically create the following sub-directories inside the
project on first use:

```
my_project/
  data/           ← internal: grades.json, annotations/
  export/         ← exported grades (grades.csv, grades.xlsx)
  export/annotated/ ← annotated PDFs
```

A ready-to-use example can be found in the `sample_project/` folder.

### config.json format

```json
{
  "export_filename_template": "{student_number}_annotated",
  "exercises": [
    {
      "name": "Exercise 1",
      "subquestions": [
        { "name": "1a", "max_points": 3 },
        { "name": "1b", "max_points": 4 }
      ]
    }
  ]
}
```

The `export_filename_template` may reference any field from the students CSV
using `{field_name}` placeholders.  Available fields: `{student_number}`,
`{last_name}`, `{first_name}`, plus any extra CSV columns.

### students.csv format

```
student_number,last_name,first_name
12345,Dupont,Jean
67890,Martin,Marie
```

Any additional columns (e.g. `participantID`, `group`) are stored and can be
shown in the grading panel.

---

## Grading workflow

1. Select a student from the grading table (right panel) or use **Shift+Alt+←/→**.
2. Use the annotation tools in the PDF toolbar (left panel) to mark the exam.
3. Enter scores directly in the grading table cells (single click or just type).
   French-style decimal commas are accepted (`1,5` is automatically converted to `1.5`).
4. Press **P** to jump focus back to the current student's grading row:
   - If no cell has been edited yet for this student → jumps to the **first** grading cell.
   - If the last-edited cell is **empty** → jumps back to that cell so you can fill it in.
   - If the last-edited cell is **filled** → advances to the **next** grading cell
     (stays on the last grading column if already at the end).
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
| ○ | **O** | Circle (red, resize handle shown at the bottom) |
| ~ | **N** | Approx/tilde (orange, "approximately correct") |
| ⊠ | **R** | Rect cross (red, X drawn inside a rectangle) |
| S | **S** | Stamp (place a preset text annotation; see Settings → Preset Annotations) |
| ⌫ | **E** | Eraser (click annotation to delete) |

For **line / arrow / circle**: click once to set the start point, click again to finish.  
Press **Esc** to cancel a shape in progress.

To **move or resize** an existing annotation: select no tool (press the active tool button
again to deselect), then hover over the annotation (a grab cursor appears) and drag it.
For circles, drag the blue handle at the bottom to resize, or drag the circumference to move.

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
| **P** | Jump grading focus to current student (see [Grading workflow](#grading-workflow) for details) |
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
| **R** | Rect cross (⊠) |
| **S** | Stamp (preset text) |
| **E** | Eraser |
| **Esc** | Cancel in-progress shape / deselect tool |

*(Pressing a tool key again while that tool is active deselects it.)*

---

## Extra CSV fields

The students CSV may contain any additional columns beyond the three required
ones.  In the grading panel click **Extra fields** to toggle their display as
read-only columns.  Extra fields are also searchable from the filter box.

---

## Settings

Open via **Project → Settings…**.  The dialog has five tabs:

| Tab | Contents |
|-----|----------|
| **Grading** | Max note, rounding step, score total (auto or manual) |
| **Export** | Filename template for annotated PDFs, cover page detail level |
| **Grading Scheme** | Exercise / subquestion editor (names & max points) |
| **Preset Annotations** | Manage the text presets used by the Stamp tool (S) |
| **Advanced** | Debug mode, high-DPI rendering, grading sheet in separate window |

### Grading sheet in separate window

Enable **"Grading sheet in separate window"** in the Advanced tab to detach the
grading spreadsheet into its own window.  This is especially useful for
dual-monitor setups: keep the PDF viewer on one screen and the grading table on
the other.  Disabling the option moves the table back into the main window.

---

## Exporting

All exports go to fixed paths inside the project directory — no file dialogs needed.

### Annotated PDFs

**Project → Export Annotated PDFs**

Output files are written to `<project>/export/annotated/`.
The filename for each student is determined by the `export_filename_template`
field in `config.json`.

### Grades

- **Project → Export Grades as CSV** → `<project>/export/grades.csv`
- **Project → Export Grades as XLSX** → `<project>/export/grades.xlsx`

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
  settings_dialog.py   – unified settings dialog (grading, export, scheme, presets, advanced)
  setup_dialog.py      – project-open dialog
sample_project/        – example project (copy and fill exams/ with your PDFs)
requirements.txt
package-app.sh
```
