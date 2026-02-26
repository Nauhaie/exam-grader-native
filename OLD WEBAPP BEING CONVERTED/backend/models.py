from pydantic import BaseModel
from typing import Optional, Dict, List


class Config(BaseModel):
    exams_dir: str
    students_csv: str
    grading_scheme: str


class Student(BaseModel):
    student_number: str
    last_name: str
    first_name: str


class Subquestion(BaseModel):
    name: str
    max_points: float


class Exercise(BaseModel):
    name: str
    subquestions: List[Subquestion]


class GradingScheme(BaseModel):
    exercises: List[Exercise]


class Annotation(BaseModel):
    id: str
    student_number: str
    page: int
    type: str  # "checkmark" | "cross" | "text" | "line" | "arrow" | "circle"
    x: float
    y: float
    text: Optional[str] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    width: Optional[float] = None


class GradeEntry(BaseModel):
    student_number: str
    subquestion_name: str
    points: float


class GradingState(BaseModel):
    grades: Dict[str, Dict[str, float]] = {}
    annotations: Dict[str, List[Annotation]] = {}


class SessionConfig(BaseModel):
    configured: bool
    students: List[Student] = []
    grading_scheme: Optional[GradingScheme] = None
    exams_dir: Optional[str] = None
