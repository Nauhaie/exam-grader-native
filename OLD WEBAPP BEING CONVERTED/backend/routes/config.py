from fastapi import APIRouter, HTTPException
from models import Config, SessionConfig
from storage import (
    save_session_config,
    load_session_config,
    parse_students_csv,
    parse_grading_scheme,
)
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/config", response_model=SessionConfig)
def post_config(config: Config):
    logger.info("POST /config — exams_dir: %s, students_csv: %s, grading_scheme: %s", config.exams_dir, config.students_csv, config.grading_scheme)
    if not os.path.isdir(config.exams_dir):
        logger.warning("POST /config — exams_dir does not exist: %s", config.exams_dir)
        raise HTTPException(status_code=400, detail=f"exams_dir does not exist: {config.exams_dir}")
    if not os.path.isfile(config.students_csv):
        logger.warning("POST /config — students_csv does not exist: %s", config.students_csv)
        raise HTTPException(status_code=400, detail=f"students_csv does not exist: {config.students_csv}")
    if not os.path.isfile(config.grading_scheme):
        logger.warning("POST /config — grading_scheme does not exist: %s", config.grading_scheme)
        raise HTTPException(status_code=400, detail=f"grading_scheme does not exist: {config.grading_scheme}")

    try:
        students = parse_students_csv(config.students_csv)
        logger.info("POST /config — parsed %d students from CSV", len(students))
    except Exception as e:
        logger.error("POST /config — failed to parse students CSV: %s", e)
        raise HTTPException(status_code=400, detail=f"Failed to parse students CSV: {e}")

    try:
        scheme = parse_grading_scheme(config.grading_scheme)
        logger.info("POST /config — parsed grading scheme with %d exercises", len(scheme.exercises))
    except Exception as e:
        logger.error("POST /config — failed to parse grading scheme: %s", e)
        raise HTTPException(status_code=400, detail=f"Failed to parse grading scheme: {e}")

    if not students:
        raise HTTPException(status_code=400, detail="Students CSV is empty or contains no valid rows")
    if not scheme.exercises:
        raise HTTPException(status_code=400, detail="Grading scheme must contain at least one exercise")

    session = SessionConfig(
        configured=True,
        students=students,
        grading_scheme=scheme,
        exams_dir=config.exams_dir,
    )
    save_session_config(session.model_dump())
    logger.info("POST /config — session configured successfully with %d students", len(students))
    return session


@router.get("/config", response_model=SessionConfig)
def get_config():
    logger.info("GET /config — loading session config")
    data = load_session_config()
    if data is None:
        logger.info("GET /config — no config found, returning unconfigured session")
        return SessionConfig(configured=False)
    cfg = SessionConfig(**data)
    logger.info("GET /config — configured: %s, students: %d", cfg.configured, len(cfg.students))
    return cfg
