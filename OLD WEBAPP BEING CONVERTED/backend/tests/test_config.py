import json


def test_get_config_unconfigured(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json()["configured"] is False


def test_post_config_missing_exams_dir(client, tmp_path):
    resp = client.post("/api/config", json={
        "exams_dir": str(tmp_path / "nonexistent"),
        "students_csv": str(tmp_path / "students.csv"),
        "grading_scheme": str(tmp_path / "scheme.json"),
    })
    assert resp.status_code == 400
    assert "exams_dir" in resp.json()["detail"]


def test_post_config_missing_students_csv(client, tmp_path):
    exams_dir = tmp_path / "exams"
    exams_dir.mkdir()
    resp = client.post("/api/config", json={
        "exams_dir": str(exams_dir),
        "students_csv": str(tmp_path / "missing.csv"),
        "grading_scheme": str(tmp_path / "scheme.json"),
    })
    assert resp.status_code == 400
    assert "students_csv" in resp.json()["detail"]


def test_post_config_valid(client, tmp_path):
    exams_dir = tmp_path / "exams"
    exams_dir.mkdir()

    students_csv = tmp_path / "students.csv"
    students_csv.write_text("student_number,last_name,first_name\n1,Dupont,Alice\n2,Martin,Bob\n")

    scheme = tmp_path / "scheme.json"
    scheme.write_text(json.dumps({
        "exercises": [{"name": "Ex1", "subquestions": [{"name": "Q1", "max_points": 4}]}]
    }))

    resp = client.post("/api/config", json={
        "exams_dir": str(exams_dir),
        "students_csv": str(students_csv),
        "grading_scheme": str(scheme),
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert len(data["students"]) == 2
    assert data["students"][0]["last_name"] == "Dupont"
    assert data["grading_scheme"]["exercises"][0]["name"] == "Ex1"


def test_get_config_after_post(client, tmp_path):
    exams_dir = tmp_path / "exams"
    exams_dir.mkdir()
    students_csv = tmp_path / "students.csv"
    students_csv.write_text("student_number,last_name,first_name\n7,Leroy,Claire\n")
    scheme = tmp_path / "scheme.json"
    scheme.write_text(json.dumps({
        "exercises": [{"name": "Math", "subquestions": [{"name": "Q1", "max_points": 5}]}]
    }))

    client.post("/api/config", json={
        "exams_dir": str(exams_dir),
        "students_csv": str(students_csv),
        "grading_scheme": str(scheme),
    })

    resp = client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json()["configured"] is True
    assert resp.json()["students"][0]["student_number"] == "7"


def test_post_config_empty_students_csv(client, tmp_path):
    exams_dir = tmp_path / "exams"
    exams_dir.mkdir()
    students_csv = tmp_path / "students.csv"
    students_csv.write_text("student_number,last_name,first_name\n")  # header only
    scheme = tmp_path / "scheme.json"
    scheme.write_text(json.dumps({
        "exercises": [{"name": "Ex1", "subquestions": [{"name": "Q1", "max_points": 4}]}]
    }))

    resp = client.post("/api/config", json={
        "exams_dir": str(exams_dir),
        "students_csv": str(students_csv),
        "grading_scheme": str(scheme),
    })
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()
