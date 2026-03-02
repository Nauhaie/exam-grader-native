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
    hi_dpr: bool = True             # use high DPI rendering (Retina); disable for speed
    grading_separate_window: bool = False  # show grading sheet in a separate window
    show_extra_fields: bool = False  # show extra CSV columns in the grading panel


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


_MIN_ROUNDING_STEP = 0.001


def compute_grade(total: float, score_total: float, max_note: float,
                  rounding: float) -> float:
    """Convert raw *total* points to a final grade.

    This is the single authoritative implementation of the grade formula used
    by the grading panel, the CSV/XLSX export, and the cover-page generator.
    """
    if score_total <= 0:
        return 0.0
    raw = (total / score_total) * max_note
    step = max(_MIN_ROUNDING_STEP, rounding)
    return round(raw / step) * step

