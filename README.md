# Exam Grader

A desktop application for grading scanned exams: view PDFs, add annotations,
enter scores and export fully annotated PDFs.

---

## Running the bundled app

If you received a pre-built bundle, just launch it directly — no Python
installation required.

| Platform | How to open |
|----------|-------------|
| **macOS** | Double-click `ExamGrader.app` (or drag it to Applications first) |
| **Windows** | Double-click `ExamGrader.exe` inside the `ExamGrader/` folder |
| **Linux** | Run `./ExamGrader` from the terminal inside the `ExamGrader/` folder |

---

## Project directory structure

The app works with a **project directory** that you provide once via
**File → Open Project…** (also shown on first launch).  The directory must
contain:

```
my_project/
  exams/          ← one PDF per student, named <student_number>.pdf
  students.csv    ← student roster
```

The app will automatically create the following sub-directories inside the
project on first use:

```
my_project/
  data/             ← internal: config.json, grades.json, annotations/
  export/           ← exported grades (grades.csv, grades.xlsx)
  export/annotated/ ← annotated PDFs
```

> **Note:** The `data/` directory is managed by the application. Do not modify
> its contents manually, and certainly not while the app is running.

A ready-to-use example can be found in the `sample_project/` folder.

### students.csv format

```
student_number,last_name,first_name
12345,Dupont,Jean
67890,Martin,Marie
```

Any additional columns (e.g. `participantID`, `group`) are stored and can be
shown as read-only columns in the grading panel and used in the filter box.
Enable **"Show extra fields in grading panel"** in
**Project → Settings… → Advanced** to display them.

---

## Grading workflow

1. Select a student from the grading table (right panel) or use **Shift+Alt+←/→**.
2. Use the annotation tools (toolbar above the PDF) to mark the exam.
3. Enter scores directly in the grading table cells (single click or just type).
   French-style decimal commas are accepted (`1,5` is automatically converted to `1.5`).
   Type **`m`** (or **`M`**) in any score cell to automatically fill in the maximum
   points for that subquestion.
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
| ○ | **O** | Ellipse (red, handles at top, right, bottom, and left for reshaping) |
| ~ | **N** | Approx/tilde (orange, "approximately correct") |
| ⊠ | **R** | Rect cross (red, X drawn inside a rectangle) |
| S | **S** | Stamp (place a preset text annotation; see Settings → Preset Annotations) |
| ⌫ | **E** | Eraser (click annotation to delete) |

For **line / arrow / ellipse**: click once to set the start point, click again to finish.  
Press **Esc** to cancel a shape in progress.

To **move or resize** an existing annotation: select no tool (press the active tool button
again to deselect), then hover over the annotation (a grab cursor appears) and drag it.
For ellipses, drag any of the four blue handles (top/right/bottom/left) to reshape, or drag the perimeter to move.

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
| **Cmd+1 / Cmd+2** (macOS) or **Ctrl+1 / Ctrl+2** | Switch between PDF Viewer and Grading Sheet windows (separate-window mode only) |
| **Ctrl + scroll** | Zoom in / out |
| Pinch gesture (macOS) | Zoom in / out |

### View

| Shortcut | Action |
|----------|--------|
| **Cmd (macOS) / Ctrl (Win/Linux) + drag** | Pan / scroll the PDF by dragging |

### Annotation tools

See the [Annotation tools](#annotation-tools) table above for keyboard shortcuts
(**V**, **X**, **T**, **L**, **A**, **O**, **N**, **R**, **S**, **E**, **Esc**).

*(Pressing a tool key again while that tool is active deselects it.)*

---

## Settings

Open via **Project → Settings…**.  The dialog has five tabs:

| Tab | Contents |
|-----|----------|
| **Grading** | Max note, rounding step, score total (auto or manual) |
| **Export** | Filename template for annotated PDFs, cover page detail level |
| **Grading Scheme** | Exercise / subquestion editor (names & max points) |
| **Preset Annotations** | Manage the text presets used by the Stamp tool (S) |
| **Advanced** | High-DPI rendering, grading sheet in separate window, show extra fields, debug mode |

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
The filename for each student is determined by the template in Project → Settings → Export tab. It may reference any field from the students CSV
using `{field_name}` placeholders.  Available fields: `{student_number}`,
`{last_name}`, `{first_name}`, plus any extra CSV columns.

### Grades

- **Project → Export Grades as CSV** → `<project>/export/grades.csv`
- **Project → Export Grades as XLSX** → `<project>/export/grades.xlsx`

---

## Running from source

For users who downloaded the source code directly.

### Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

```bash
python -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

### Starting the app

```bash
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
cd app
python main.py
```

---

## Packaging as a standalone app

Use the included `package-app.sh` script.  It creates a self-contained
application bundle in `dist/` using PyInstaller.

```bash
# Install packaging tool (once, inside the venv)
pip install pyinstaller

# Build
bash package-app.sh
```

| Platform | Output |
|----------|--------|
| macOS | `dist/ExamGrader.app` (drag to Applications) |
| Windows | `dist/ExamGrader/ExamGrader.exe` |
| Linux | `dist/ExamGrader/ExamGrader` |

### Icon management

`icon.svg`, `icon.png` and `icon.icns` are already committed to the repository,
so no action is needed in normal development.

Only run `convert-icon.sh` if you change `icon.svg`, then commit the
regenerated `icon.png` / `icon.icns`:

```bash
bash convert-icon.sh
```

See `convert-icon.sh` for tool requirements and details.

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
