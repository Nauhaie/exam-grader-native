from fastapi import APIRouter, HTTPException
from models import Student
from storage import load_session_config
from typing import List

router = APIRouter()


@router.get("/students", response_model=List[Student])
def get_students():
    data = load_session_config()
    if not data or not data.get("configured"):
        raise HTTPException(status_code=400, detail="Session not configured")
    return data.get("students", [])
