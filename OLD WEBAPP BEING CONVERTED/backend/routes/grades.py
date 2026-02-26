from fastapi import APIRouter, HTTPException
from models import GradeEntry
from storage import load_grades, save_grades, load_session_config
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/grades")
def get_grades():
    logger.info("GET /grades — loading all grades")
    grades = load_grades()
    logger.info("GET /grades — returned grades for %d students", len(grades))
    return grades


@router.post("/grades")
def post_grade(entry: GradeEntry):
    logger.info("POST /grades — student: %s, subquestion: %s, points: %s", entry.student_number, entry.subquestion_name, entry.points)
    grades = load_grades()
    if entry.student_number not in grades:
        grades[entry.student_number] = {}
    grades[entry.student_number][entry.subquestion_name] = entry.points
    save_grades(grades)
    logger.info("POST /grades — saved grade for student %s", entry.student_number)
    return {"status": "ok"}
