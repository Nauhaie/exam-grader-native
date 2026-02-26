"""Data persistence: load/save grades, annotations, session config."""
import json
import os
from typing import Dict, List, Optional

from models import Annotation, Exercise, GradingScheme, Student, Subquestion


# ── App-level session config (persists which project dir was last opened) ─────

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DATA_DIR = os.path.join(os.path.dirname(_APP_DIR), "data")
SESSION_CONFIG_PATH = os.path.join(_APP_DATA_DIR, "session_config.json")

# ── Project-dir-derived paths (set via set_project_dir) ──────────────────────

_active_project_dir: Optional[str] = None
DATA_DIR: str = ""
GRADES_PATH: str = ""
ANNOTATIONS_DIR: str = ""
EXPORT_DIR: str = ""
ANNOTATED_EXPORT_DIR: str = ""


def set_project_dir(project_dir: str) -> None:
    """Configure all data paths to use *project_dir* as the root."""
    global _active_project_dir, DATA_DIR, GRADES_PATH, ANNOTATIONS_DIR
    global EXPORT_DIR, ANNOTATED_EXPORT_DIR
    _active_project_dir = os.path.abspath(project_dir)
    DATA_DIR = os.path.join(_active_project_dir, "data")
    GRADES_PATH = os.path.join(DATA_DIR, "grades.json")
    ANNOTATIONS_DIR = os.path.join(DATA_DIR, "annotations")
    EXPORT_DIR = os.path.join(_active_project_dir, "export")
    ANNOTATED_EXPORT_DIR = os.path.join(EXPORT_DIR, "annotated")


def get_project_dir() -> Optional[str]:
    return _active_project_dir


def _require_project_dir(fn_name: str) -> None:
    """Raise RuntimeError if no project directory has been configured."""
    if not _active_project_dir:
        raise RuntimeError(
            f"data_store.{fn_name}() called before set_project_dir(). "
            "Open a project first."
        )


def ensure_data_dirs():
    _require_project_dir("ensure_data_dirs")
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(ANNOTATIONS_DIR, exist_ok=True)
    os.makedirs(EXPORT_DIR, exist_ok=True)
    os.makedirs(ANNOTATED_EXPORT_DIR, exist_ok=True)


# ── Session config ────────────────────────────────────────────────────────────

def load_session_config() -> Optional[dict]:
    if not os.path.exists(SESSION_CONFIG_PATH):
        return None
    with open(SESSION_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_session_config(project_dir: str):
    os.makedirs(_APP_DATA_DIR, exist_ok=True)
    config = {"project_dir": os.path.abspath(project_dir)}
    with open(SESSION_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


# ── Project config.json (grading scheme + export template) ───────────────────

def load_project_config(project_dir: str) -> dict:
    """Read *project_dir*/config.json and return the raw dict."""
    path = os.path.join(project_dir, "config.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_grading_scheme_from_config(config_data: dict) -> GradingScheme:
    """Build a GradingScheme from a parsed config dict."""
    exercises = []
    for ex_data in config_data.get("exercises", []):
        subquestions = [
            Subquestion(name=sq["name"], max_points=float(sq["max_points"]))
            for sq in ex_data.get("subquestions", [])
        ]
        exercises.append(Exercise(name=ex_data["name"], subquestions=subquestions))
    return GradingScheme(exercises=exercises)


def get_export_filename_template(config_data: dict) -> str:
    """Return the export filename template, with a sensible default."""
    return config_data.get("export_filename_template", "{student_number}_annotated")


# ── Students CSV ──────────────────────────────────────────────────────────────

def load_students(csv_path: str) -> List[Student]:
    import csv
    _CORE = {"student_number", "last_name", "first_name"}
    students = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            extra = {k: str(v).strip() for k, v in row.items() if k not in _CORE}
            students.append(Student(
                student_number=str(row["student_number"]).strip(),
                last_name=str(row["last_name"]).strip(),
                first_name=str(row["first_name"]).strip(),
                extra_fields=extra,
            ))
    return students


# ── Grades ────────────────────────────────────────────────────────────────────

def load_grades() -> Dict[str, dict]:
    """Return { student_number: { subquestion_name: points } }"""
    _require_project_dir("load_grades")
    if not os.path.exists(GRADES_PATH):
        return {}
    with open(GRADES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_grades(grades: Dict[str, dict]):
    _require_project_dir("save_grades")
    ensure_data_dirs()
    with open(GRADES_PATH, "w", encoding="utf-8") as f:
        json.dump(grades, f, indent=2)


# ── Annotations ───────────────────────────────────────────────────────────────

def load_annotations(student_number: str) -> List[Annotation]:
    _require_project_dir("load_annotations")
    path = os.path.join(ANNOTATIONS_DIR, f"{student_number}.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    annotations = []
    for item in data:
        annotations.append(Annotation(
            page=item["page"],
            type=item["type"],
            x=item["x"],
            y=item["y"],
            text=item.get("text"),
            x2=item.get("x2"),
            y2=item.get("y2"),
            width=item.get("width"),
        ))
    return annotations


def save_annotations(student_number: str, annotations: List[Annotation]):
    _require_project_dir("save_annotations")
    ensure_data_dirs()
    path = os.path.join(ANNOTATIONS_DIR, f"{student_number}.json")
    data = []
    for ann in annotations:
        item = {"page": ann.page, "type": ann.type, "x": ann.x, "y": ann.y}
        if ann.text is not None:
            item["text"] = ann.text
        if ann.x2 is not None:
            item["x2"] = ann.x2
        if ann.y2 is not None:
            item["y2"] = ann.y2
        if ann.width is not None:
            item["width"] = ann.width
        data.append(item)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
