"""Data models for exam grader."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Student:
    student_number: str
    last_name: str
    first_name: str
    extra_fields: Dict[str, str] = field(default_factory=dict)

    def display_name(self) -> str:
        return f"{self.last_name} {self.first_name} (#{self.student_number})"


@dataclass
class Annotation:
    page: int  # 0-based page index
    type: str  # "checkmark", "cross", "text", "line", "arrow", "circle", "rectcross"
    x: float   # fractional coordinate 0.0–1.0
    y: float   # fractional coordinate 0.0–1.0
    text: Optional[str] = None   # only for type "text"
    x2: Optional[float] = None   # end point (line/arrow) or edge point (circle)
    y2: Optional[float] = None   # end point (line/arrow) or edge point (circle)
    width: Optional[float] = None  # text box width as fraction of page width
    # height is NOT stored; it is always computed automatically from content


@dataclass
class GradingSettings:
    max_note: float = 20.0          # maximum grade (e.g. 20 for French system)
    rounding: float = 0.5           # round to nearest multiple of this value
    score_total: Optional[float] = None  # denominator; None = sum of all exam points
    debug_mode: bool = False        # print debug messages and write .log files
    cover_page_detail: bool = False # cover page: True = show subquestion detail, False = per-exercise only


@dataclass
class Subquestion:
    name: str
    max_points: float


@dataclass
class Exercise:
    name: str
    subquestions: List[Subquestion] = field(default_factory=list)


@dataclass
class GradingScheme:
    exercises: List[Exercise] = field(default_factory=list)

    def all_subquestions(self) -> List[tuple]:
        """Return list of (exercise_name, subquestion) tuples."""
        result = []
        for ex in self.exercises:
            for sq in ex.subquestions:
                result.append((ex.name, sq))
        return result

    def max_total(self) -> float:
        return sum(sq.max_points for _, sq in self.all_subquestions())


@dataclass
class Grade:
    student_number: str
    scores: dict = field(default_factory=dict)  # { subquestion_name: points }

    def total(self) -> float:
        return sum(v for v in self.scores.values() if v is not None)

    def grade_out_of_20(self, max_total: float) -> float:
        if max_total == 0:
            return 0.0
        return round((self.total() / max_total) * 20, 2)
