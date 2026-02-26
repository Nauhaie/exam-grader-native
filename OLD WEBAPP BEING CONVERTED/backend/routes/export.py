from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from storage import load_grades, load_session_config
import csv
import io
import zipfile
import os
import openpyxl

router = APIRouter()


def _build_rows(session_data: dict, grades: dict):
    students = session_data.get("students", [])
    scheme = session_data.get("grading_scheme", {})
    exercises = scheme.get("exercises", [])

    subquestions = []
    for ex in exercises:
        for sq in ex.get("subquestions", []):
            subquestions.append(sq["name"])

    rows = []
    for student in students:
        sn = student["student_number"]
        student_grades = grades.get(sn, {})
        row = {
            "student_number": sn,
            "last_name": student["last_name"],
            "first_name": student["first_name"],
        }
        for sq in subquestions:
            row[sq] = student_grades.get(sq, "")
        rows.append(row)

    return rows, subquestions


@router.get("/export/grades/csv")
def export_grades_csv():
    session_data = load_session_config()
    if not session_data or not session_data.get("configured"):
        raise HTTPException(status_code=400, detail="Session not configured")

    grades = load_grades()
    rows, subquestions = _build_rows(session_data, grades)

    output = io.StringIO()
    fieldnames = ["student_number", "last_name", "first_name"] + subquestions
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=grades.csv"},
    )


@router.get("/export/grades/xlsx")
def export_grades_xlsx():
    session_data = load_session_config()
    if not session_data or not session_data.get("configured"):
        raise HTTPException(status_code=400, detail="Session not configured")

    grades = load_grades()
    rows, subquestions = _build_rows(session_data, grades)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Grades"

    headers = ["student_number", "last_name", "first_name"] + subquestions
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h, "") for h in headers])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=grades.xlsx"},
    )


@router.post("/export/pdfs")
def export_pdfs():
    """Export original PDFs as a ZIP archive. Annotation baking is performed client-side."""
    session_data = load_session_config()
    if not session_data or not session_data.get("configured"):
        raise HTTPException(status_code=400, detail="Session not configured")

    exams_dir = session_data.get("exams_dir", "")
    students = session_data.get("students", [])

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for student in students:
            sn = student["student_number"]
            pdf_path = os.path.join(exams_dir, f"{sn}.pdf")
            if os.path.isfile(pdf_path):
                zf.write(pdf_path, arcname=f"{sn}.pdf")

    zip_buffer.seek(0)
    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=annotated_exams.zip"},
    )
