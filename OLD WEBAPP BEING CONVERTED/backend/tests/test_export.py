import json
from routes.export import _build_rows


# ── pure unit tests for _build_rows ──────────────────────────────────────────

SCHEME = {
    "exercises": [
        {"name": "Ex1", "subquestions": [{"name": "Q1", "max_points": 4}, {"name": "Q2", "max_points": 6}]},
        {"name": "Ex2", "subquestions": [{"name": "Q3", "max_points": 10}]},
    ]
}
STUDENTS = [
    {"student_number": "1", "last_name": "Dupont", "first_name": "Alice"},
    {"student_number": "2", "last_name": "Martin", "first_name": "Bob"},
]
SESSION = {"configured": True, "students": STUDENTS, "grading_scheme": SCHEME}


def test_build_rows_no_grades():
    rows, subquestions = _build_rows(SESSION, {})
    assert subquestions == ["Q1", "Q2", "Q3"]
    assert len(rows) == 2
    assert rows[0]["student_number"] == "1"
    assert rows[0]["Q1"] == ""
    assert rows[0]["Q3"] == ""


def test_build_rows_with_partial_grades():
    grades = {"1": {"Q1": 3.0, "Q3": 7.5}}
    rows, _ = _build_rows(SESSION, grades)
    assert rows[0]["Q1"] == 3.0
    assert rows[0]["Q2"] == ""   # not yet graded
    assert rows[0]["Q3"] == 7.5
    assert rows[1]["Q1"] == ""   # student 2 has no grades


def test_build_rows_preserves_student_order():
    rows, _ = _build_rows(SESSION, {})
    assert [r["student_number"] for r in rows] == ["1", "2"]


# ── integration tests for export endpoints ───────────────────────────────────

def _configure(client, tmp_path):
    exams_dir = tmp_path / "exams"
    exams_dir.mkdir()
    students_csv = tmp_path / "students.csv"
    students_csv.write_text("student_number,last_name,first_name\n1,Dupont,Alice\n2,Martin,Bob\n")
    scheme = tmp_path / "scheme.json"
    scheme.write_text(json.dumps(SCHEME))
    client.post("/api/config", json={
        "exams_dir": str(exams_dir),
        "students_csv": str(students_csv),
        "grading_scheme": str(scheme),
    })


def test_export_csv_not_configured(client):
    resp = client.get("/api/export/grades/csv")
    assert resp.status_code == 400


def test_export_csv_returns_csv(client, tmp_path):
    _configure(client, tmp_path)
    client.post("/api/grades", json={"student_number": "1", "subquestion_name": "Q1", "points": 3.0})

    resp = client.get("/api/export/grades/csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    text = resp.text
    assert "Dupont" in text
    assert "3.0" in text


def test_export_xlsx_not_configured(client):
    resp = client.get("/api/export/grades/xlsx")
    assert resp.status_code == 400


def test_export_xlsx_returns_xlsx(client, tmp_path):
    _configure(client, tmp_path)
    resp = client.get("/api/export/grades/xlsx")
    assert resp.status_code == 200
    content_type = resp.headers["content-type"]
    assert "spreadsheetml" in content_type or "officedocument" in content_type
    assert len(resp.content) > 0
