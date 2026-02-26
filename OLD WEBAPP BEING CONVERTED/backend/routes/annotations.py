from fastapi import APIRouter, HTTPException
from models import Annotation
from storage import load_annotations, save_annotations
from typing import List
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/annotations/{student_number}", response_model=List[Annotation])
def get_annotations(student_number: str):
    logger.info("GET /annotations/%s — loading annotations", student_number)
    annotations = load_annotations(student_number)
    logger.info("GET /annotations/%s — returned %d annotations", student_number, len(annotations))
    return annotations


@router.post("/annotations/{student_number}")
def post_annotations(student_number: str, annotations: List[Annotation]):
    logger.info("POST /annotations/%s — saving %d annotations", student_number, len(annotations))
    save_annotations(student_number, [a.model_dump() for a in annotations])
    logger.info("POST /annotations/%s — saved successfully", student_number)
    return {"status": "ok"}


@router.delete("/annotations/{student_number}/{annotation_id}")
def delete_annotation(student_number: str, annotation_id: str):
    logger.info("DELETE /annotations/%s/%s — deleting annotation", student_number, annotation_id)
    annotations = load_annotations(student_number)
    updated = [a for a in annotations if a.get("id") != annotation_id]
    save_annotations(student_number, updated)
    logger.info("DELETE /annotations/%s/%s — deleted, remaining: %d", student_number, annotation_id, len(updated))
    return {"status": "ok"}
