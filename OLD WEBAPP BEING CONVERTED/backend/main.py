from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import time
import logging

from routes import config, students, grades, annotations, exams, export, grading_scheme

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = "./data"
os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI(title="Exam Grader API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.perf_counter()
    logger.info("REQUEST  %s %s", request.method, request.url.path)
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("RESPONSE %s %s — status: %d, time: %.1fms", request.method, request.url.path, response.status_code, elapsed_ms)
    return response

app.include_router(config.router, prefix="/api")
app.include_router(students.router, prefix="/api")
app.include_router(grades.router, prefix="/api")
app.include_router(annotations.router, prefix="/api")
app.include_router(exams.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(grading_scheme.router, prefix="/api")


@app.get("/")
def root():
    return {"status": "ok", "message": "Exam Grader API"}
