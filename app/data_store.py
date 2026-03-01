"""Data persistence: load/save grades, annotations, session config."""
import csv
import json
import os
from typing import Dict, List, Optional

from models import Annotation, Exercise, GradingScheme, GradingSettings, Student, Subquestion


# ── Debug logging ─────────────────────────────────────────────────────────────

_debug: bool = False

# Suppress noisy MuPDF error/warning output by default; set_debug(True) re-enables it.
try:
    import fitz as _fitz
    _fitz.TOOLS.mupdf_display_errors(False)
    _fitz.TOOLS.mupdf_display_warnings(False)
except (ImportError, AttributeError):
    pass


def set_debug(enabled: bool) -> None:
    """Enable or disable debug logging to the terminal.

    Also toggles MuPDF error/warning display so that noisy messages from
    slightly-corrupt PDFs are hidden unless the user opts into debug mode.
    """
    global _debug
    _debug = enabled
    try:
        import fitz
        fitz.TOOLS.mupdf_display_errors(enabled)
        fitz.TOOLS.mupdf_display_warnings(enabled)
    except (ImportError, AttributeError):
        pass
    if enabled:
        print("[DEBUG] Debug mode enabled")


def dbg(msg: str) -> None:
    """Print a debug message to the terminal if debug mode is on."""
    if _debug:
        print(f"[DEBUG] {msg}")


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
ANNOTATED_LOGS_DIR: str = ""


def set_project_dir(project_dir: str) -> None:
    """Configure all data paths to use *project_dir* as the root."""
    global _active_project_dir, DATA_DIR, GRADES_PATH, ANNOTATIONS_DIR
    global EXPORT_DIR, ANNOTATED_EXPORT_DIR, ANNOTATED_LOGS_DIR
    _active_project_dir = os.path.abspath(project_dir)
    DATA_DIR = os.path.join(_active_project_dir, "data")
    GRADES_PATH = os.path.join(DATA_DIR, "grades.json")
    ANNOTATIONS_DIR = os.path.join(DATA_DIR, "annotations")
    EXPORT_DIR = os.path.join(_active_project_dir, "export")
    ANNOTATED_EXPORT_DIR = os.path.join(EXPORT_DIR, "annotated")
    ANNOTATED_LOGS_DIR = os.path.join(ANNOTATED_EXPORT_DIR, "logs")
    dbg(f"Project dir set to: {_active_project_dir}")
    dbg(f"  DATA_DIR         = {DATA_DIR}")
    dbg(f"  GRADES_PATH      = {GRADES_PATH}")
    dbg(f"  ANNOTATIONS_DIR  = {ANNOTATIONS_DIR}")
    dbg(f"  EXPORT_DIR       = {EXPORT_DIR}")
    dbg(f"  ANNOTATED_EXPORT = {ANNOTATED_EXPORT_DIR}")
    dbg(f"  ANNOTATED_LOGS   = {ANNOTATED_LOGS_DIR}")


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
    dbg(f"Ensured data dirs exist under {_active_project_dir}")


# ── Session config ────────────────────────────────────────────────────────────

def load_session_config() -> Optional[dict]:
    dbg(f"Loading session config from {SESSION_CONFIG_PATH}")
    if not os.path.exists(SESSION_CONFIG_PATH):
        dbg("  Session config file not found")
        return None
    with open(SESSION_CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    dbg(f"  Session config loaded: {config}")
    return config


def save_session_config(project_dir: str):
    os.makedirs(_APP_DATA_DIR, exist_ok=True)
    config = {"project_dir": os.path.abspath(project_dir)}
    with open(SESSION_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    dbg(f"Session config saved: {config}")


# ── Project config.json (grading scheme + export template) ───────────────────

def load_project_config(project_dir: str) -> dict:
    """Read *project_dir*/config.json and return the raw dict."""
    path = os.path.join(project_dir, "config.json")
    dbg(f"Loading project config from {path}")
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    dbg(f"  Project config keys: {list(config.keys())}")
    return config


def save_project_config(project_dir: str, config_data: dict) -> None:
    """Write *config_data* back to *project_dir*/config.json."""
    path = os.path.join(project_dir, "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)
        f.write("\n")
    dbg(f"Project config saved to {path}")


def load_grading_scheme_from_config(config_data: dict) -> GradingScheme:
    """Build a GradingScheme from a parsed config dict."""
    exercises = []
    for ex_data in config_data.get("exercises", []):
        subquestions = [
            Subquestion(name=sq["name"], max_points=float(sq["max_points"]))
            for sq in ex_data.get("subquestions", [])
        ]
        exercises.append(Exercise(name=ex_data["name"], subquestions=subquestions))
    scheme = GradingScheme(exercises=exercises)
    dbg(f"Grading scheme loaded: {len(exercises)} exercise(s), "
        f"{sum(len(ex.subquestions) for ex in exercises)} subquestion(s)")
    return scheme


def load_grading_settings_from_config(config_data: dict) -> GradingSettings:
    """Build a GradingSettings from a parsed config dict."""
    gs = config_data.get("grading_settings", {})
    raw_st = gs.get("score_total")
    settings = GradingSettings(
        max_note=float(gs.get("max_note", 20.0)),
        rounding=float(gs.get("rounding", 0.5)),
        score_total=float(raw_st) if raw_st is not None else None,
        debug_mode=bool(gs.get("debug_mode", False)),
        cover_page_detail=bool(gs.get("cover_page_detail", False)),
        hi_dpr=bool(gs.get("hi_dpr", True)),
        grading_separate_window=bool(gs.get("grading_separate_window", False)),
        show_extra_fields=bool(gs.get("show_extra_fields", False)),
    )
    set_debug(settings.debug_mode)
    dbg(f"Grading settings loaded: max_note={settings.max_note}, "
        f"rounding={settings.rounding}, score_total={settings.score_total}, "
        f"debug_mode={settings.debug_mode}")
    return settings


def save_grading_settings_to_config(config_data: dict, settings: GradingSettings) -> None:
    """Write *settings* into *config_data* in-place (call save_project_config to persist)."""
    config_data["grading_settings"] = {
        "max_note": settings.max_note,
        "rounding": settings.rounding,
        "score_total": settings.score_total,
        "debug_mode": settings.debug_mode,
        "cover_page_detail": settings.cover_page_detail,
        "hi_dpr": settings.hi_dpr,
        "grading_separate_window": settings.grading_separate_window,
        "show_extra_fields": settings.show_extra_fields,
    }


def get_export_filename_template(config_data: dict) -> str:
    """Return the export filename template, with a sensible default."""
    return config_data.get("export_filename_template", "{student_number}_annotated")


def save_export_template_to_config(config_data: dict, template: str) -> None:
    """Write *template* into *config_data* in-place."""
    config_data["export_filename_template"] = template


def save_grading_scheme_to_config(config_data: dict, scheme: GradingScheme) -> None:
    """Write *scheme* into *config_data* in-place (call save_project_config to persist)."""
    config_data["exercises"] = [
        {
            "name": ex.name,
            "subquestions": [
                {"name": sq.name, "max_points": sq.max_points}
                for sq in ex.subquestions
            ],
        }
        for ex in scheme.exercises
    ]


def load_preset_annotations(config_data: dict) -> List[str]:
    """Return the list of preset annotation texts from the config."""
    return list(config_data.get("preset_annotations", []))


def save_preset_annotations_to_config(config_data: dict, presets: List[str]) -> None:
    """Write *presets* into *config_data* in-place."""
    config_data["preset_annotations"] = list(presets)


# ── Students CSV ──────────────────────────────────────────────────────────────

def load_students(csv_path: str) -> List[Student]:
    dbg(f"Loading students from {csv_path}")
    _CORE = {"student_number", "last_name", "first_name"}
    students = []
    seen_ids: set = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sn = str(row["student_number"]).strip()
            if sn in seen_ids:
                raise ValueError(
                    f"Duplicate student number '{sn}' in {csv_path}"
                )
            seen_ids.add(sn)
            extra = {k: str(v).strip() for k, v in row.items() if k not in _CORE}
            students.append(Student(
                student_number=sn,
                last_name=str(row["last_name"]).strip(),
                first_name=str(row["first_name"]).strip(),
                extra_fields=extra,
            ))
    dbg(f"  Loaded {len(students)} student(s)")
    return students


# ── Grades ────────────────────────────────────────────────────────────────────

def load_grades() -> Dict[str, dict]:
    """Return { student_number: { subquestion_name: points } }"""
    _require_project_dir("load_grades")
    dbg(f"Loading grades from {GRADES_PATH}")
    if not os.path.exists(GRADES_PATH):
        dbg("  Grades file not found, returning empty")
        return {}
    with open(GRADES_PATH, "r", encoding="utf-8") as f:
        grades = json.load(f)
    dbg(f"  Loaded grades for {len(grades)} student(s)")
    return grades


def save_grades(grades: Dict[str, dict]):
    _require_project_dir("save_grades")
    ensure_data_dirs()
    with open(GRADES_PATH, "w", encoding="utf-8") as f:
        json.dump(grades, f, indent=2)
    dbg(f"Grades saved for {len(grades)} student(s)")


# ── Annotations ───────────────────────────────────────────────────────────────

def load_annotations(student_number: str) -> List[Annotation]:
    _require_project_dir("load_annotations")
    path = os.path.join(ANNOTATIONS_DIR, f"{student_number}.json")
    dbg(f"Loading annotations for student {student_number} from {path}")
    if not os.path.exists(path):
        dbg("  Annotations file not found, returning empty")
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
            # height is intentionally not loaded; it is always computed from content
        ))
    dbg(f"  Loaded {len(annotations)} annotation(s)")
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
        # height is intentionally NOT saved; it is always computed from content
        data.append(item)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    dbg(f"Annotations saved for student {student_number}: {len(annotations)} annotation(s)")
