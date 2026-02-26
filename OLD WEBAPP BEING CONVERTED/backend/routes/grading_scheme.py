from fastapi import APIRouter, HTTPException
from models import GradingScheme
from storage import save_grading_scheme, load_grading_scheme
import json
import os

router = APIRouter()

SAMPLE_SCHEME_PATH = "./sample_data/grading_scheme.json"


@router.get("/grading-scheme", response_model=GradingScheme)
def get_grading_scheme():
    data = load_grading_scheme()
    if data is None:
        raise HTTPException(status_code=404, detail="No grading scheme found")
    return GradingScheme(**data)


@router.post("/grading-scheme", response_model=GradingScheme)
def post_grading_scheme(scheme: GradingScheme):
    save_grading_scheme(scheme.model_dump())
    return scheme


@router.get("/grading-scheme/sample", response_model=GradingScheme)
def get_sample_grading_scheme():
    if not os.path.exists(SAMPLE_SCHEME_PATH):
        raise HTTPException(status_code=404, detail="Sample grading scheme not found")
    with open(SAMPLE_SCHEME_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return GradingScheme(**data)
