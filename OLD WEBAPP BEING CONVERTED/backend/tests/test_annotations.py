def test_get_annotations_empty(client):
    resp = client.get("/api/annotations/99")
    assert resp.status_code == 200
    assert resp.json() == []


def test_post_and_get_annotations(client):
    annotation = {
        "id": "abc",
        "student_number": "99",
        "page": 1,
        "type": "checkmark",
        "x": 0.5,
        "y": 0.3,
    }
    resp = client.post("/api/annotations/99", json=[annotation])
    assert resp.status_code == 200

    saved = client.get("/api/annotations/99").json()
    assert len(saved) == 1
    assert saved[0]["id"] == "abc"
    assert saved[0]["type"] == "checkmark"


def test_post_annotations_overwrites(client):
    ann_a = {"id": "a", "student_number": "1", "page": 1, "type": "cross", "x": 0.1, "y": 0.2}
    ann_b = {"id": "b", "student_number": "1", "page": 1, "type": "checkmark", "x": 0.5, "y": 0.5}

    client.post("/api/annotations/1", json=[ann_a])
    client.post("/api/annotations/1", json=[ann_b])  # full replace

    saved = client.get("/api/annotations/1").json()
    assert len(saved) == 1
    assert saved[0]["id"] == "b"


def test_delete_annotation(client):
    annotations = [
        {"id": "keep", "student_number": "5", "page": 1, "type": "cross", "x": 0.1, "y": 0.2},
        {"id": "remove", "student_number": "5", "page": 1, "type": "text", "x": 0.3, "y": 0.4, "text": "hi"},
    ]
    client.post("/api/annotations/5", json=annotations)

    resp = client.delete("/api/annotations/5/remove")
    assert resp.status_code == 200

    remaining = client.get("/api/annotations/5").json()
    assert len(remaining) == 1
    assert remaining[0]["id"] == "keep"


def test_delete_nonexistent_annotation_is_noop(client):
    client.post("/api/annotations/7", json=[
        {"id": "x", "student_number": "7", "page": 1, "type": "cross", "x": 0.0, "y": 0.0}
    ])
    resp = client.delete("/api/annotations/7/ghost")
    assert resp.status_code == 200

    remaining = client.get("/api/annotations/7").json()
    assert len(remaining) == 1
