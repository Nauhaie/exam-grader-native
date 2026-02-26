"""Data persistence: load/save grades, annotations, session config."""
import json
import os
from typing import Dict, List, Optional

from models import Annotation, Exercise, GradingScheme, Student, Subquestion


# Resolve data directory relative to this file's location
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_APP_DIR)
DATA_DIR = os.path.join(_PROJECT_DIR, "data")
SESSION_CONFIG_PATH = os.path.join(DATA_DIR, "session_config.json")
GRADES_PATH = os.path.join(DATA_DIR, "grades.json")
ANNOTATIONS_DIR = os.path.join(DATA_DIR, "annotations")


def ensure_data_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(ANNOTATIONS_DIR, exist_ok=True)


# ── Session config ────────────────────────────────────────────────────────────

def load_session_config() -> Optional[dict]:
    if not os.path.exists(SESSION_CONFIG_PATH):
        return None
    with open(SESSION_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_session_config(exams_dir: str, students_csv: str, grading_scheme: str):
    ensure_data_dirs()
    config = {
        "exams_dir": os.path.abspath(exams_dir),
        "students_csv": os.path.abspath(students_csv),
        "grading_scheme": os.path.abspath(grading_scheme),
    }
    with open(SESSION_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


# ── Students CSV ──────────────────────────────────────────────────────────────

def load_students(csv_path: str) -> List[Student]:
    import csv
    students = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            students.append(Student(
                student_number=str(row["student_number"]).strip(),
                last_name=str(row["last_name"]).strip(),
                first_name=str(row["first_name"]).strip(),
            ))
    return students


# ── Grading scheme JSON ───────────────────────────────────────────────────────

def load_grading_scheme(json_path: str) -> GradingScheme:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    exercises = []
    for ex_data in data.get("exercises", []):
        subquestions = [
            Subquestion(name=sq["name"], max_points=float(sq["max_points"]))
            for sq in ex_data.get("subquestions", [])
        ]
        exercises.append(Exercise(name=ex_data["name"], subquestions=subquestions))
    return GradingScheme(exercises=exercises)


# ── Grades ────────────────────────────────────────────────────────────────────

def load_grades() -> Dict[str, dict]:
    """Return { student_number: { subquestion_name: points } }"""
    if not os.path.exists(GRADES_PATH):
        return {}
    with open(GRADES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_grades(grades: Dict[str, dict]):
    ensure_data_dirs()
    with open(GRADES_PATH, "w", encoding="utf-8") as f:
        json.dump(grades, f, indent=2)


# ── Annotations ───────────────────────────────────────────────────────────────

def load_annotations(student_number: str) -> List[Annotation]:
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
