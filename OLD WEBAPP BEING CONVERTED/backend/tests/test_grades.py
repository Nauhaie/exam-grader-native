def test_get_grades_empty(client):
    resp = client.get("/api/grades")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_post_grade_then_get(client):
    resp = client.post("/api/grades", json={
        "student_number": "42",
        "subquestion_name": "1a",
        "points": 3.5,
    })
    assert resp.status_code == 200

    grades = client.get("/api/grades").json()
    assert grades["42"]["1a"] == 3.5


def test_post_grade_overwrites_previous(client):
    payload = {"student_number": "42", "subquestion_name": "1a", "points": 3.0}
    client.post("/api/grades", json=payload)
    client.post("/api/grades", json={**payload, "points": 5.0})

    grades = client.get("/api/grades").json()
    assert grades["42"]["1a"] == 5.0


def test_multiple_students_and_subquestions(client):
    entries = [
        {"student_number": "1", "subquestion_name": "Q1", "points": 2.0},
        {"student_number": "1", "subquestion_name": "Q2", "points": 4.0},
        {"student_number": "2", "subquestion_name": "Q1", "points": 1.0},
    ]
    for e in entries:
        client.post("/api/grades", json=e)

    grades = client.get("/api/grades").json()
    assert grades["1"]["Q1"] == 2.0
    assert grades["1"]["Q2"] == 4.0
    assert grades["2"]["Q1"] == 1.0
    assert "Q2" not in grades.get("2", {})
