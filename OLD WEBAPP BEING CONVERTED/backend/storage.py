import json
import csv
import os
from typing import List, Optional
from models import Student, GradingScheme, SessionConfig, Annotation, GradeEntry

DATA_DIR = "./data"


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def save_session_config(config: dict):
    _ensure_data_dir()
    with open(os.path.join(DATA_DIR, "session_config.json"), "w") as f:
        json.dump(config, f, indent=2)


def load_session_config() -> Optional[dict]:
    path = os.path.join(DATA_DIR, "session_config.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def save_grades(grades: dict):
    _ensure_data_dir()
    with open(os.path.join(DATA_DIR, "grades.json"), "w") as f:
        json.dump(grades, f, indent=2)


def load_grades() -> dict:
    path = os.path.join(DATA_DIR, "grades.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_annotations(student_number: str, annotations: list):
    _ensure_data_dir()
    annotations_dir = os.path.join(DATA_DIR, "annotations")
    os.makedirs(annotations_dir, exist_ok=True)
    with open(os.path.join(annotations_dir, f"{student_number}.json"), "w") as f:
        json.dump(annotations, f, indent=2)


def load_annotations(student_number: str) -> list:
    path = os.path.join(DATA_DIR, "annotations", f"{student_number}.json")
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return json.load(f)


def parse_students_csv(csv_path: str) -> List[Student]:
    students = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            students.append(Student(
                student_number=str(row["student_number"]).strip(),
                last_name=row["last_name"].strip(),
                first_name=row["first_name"].strip(),
            ))
    return students


def save_grading_scheme(scheme: dict):
    _ensure_data_dir()
    with open(os.path.join(DATA_DIR, "grading_scheme.json"), "w") as f:
        json.dump(scheme, f, indent=2)


def load_grading_scheme() -> Optional[dict]:
    path = os.path.join(DATA_DIR, "grading_scheme.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def parse_grading_scheme(scheme_path: str) -> GradingScheme:
    with open(scheme_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return GradingScheme(**data)
