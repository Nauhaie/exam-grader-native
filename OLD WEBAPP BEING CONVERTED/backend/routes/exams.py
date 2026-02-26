from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from storage import load_session_config
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/exams/{student_number}")
def get_exam(student_number: str):
    logger.info("GET /exams/%s — fetching PDF", student_number)
    data = load_session_config()
    if not data or not data.get("configured"):
        logger.warning("GET /exams/%s — session not configured", student_number)
        raise HTTPException(status_code=400, detail="Session not configured")

    exams_dir = data.get("exams_dir", "")
    pdf_path = os.path.join(exams_dir, f"{student_number}.pdf")
    exists = os.path.isfile(pdf_path)
    file_size = os.path.getsize(pdf_path) if exists else None
    logger.info("GET /exams/%s — path: %s, exists: %s, size: %s bytes", student_number, pdf_path, exists, file_size)

    if not exists:
        logger.warning("GET /exams/%s — PDF not found at %s", student_number, pdf_path)
        raise HTTPException(status_code=404, detail=f"Exam PDF not found for student {student_number}")

    logger.info("GET /exams/%s — serving PDF (%s bytes)", student_number, file_size)
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{student_number}.pdf")
