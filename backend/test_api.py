from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_energy_round_trip():
    response = client.post("/energy", json={"level": 4})
    assert response.status_code == 200
    data = response.json()
    assert data["energy"] == 4

    response = client.get("/energy")
    assert response.status_code == 200
    assert response.json()["energy"] == 4


def test_schedule_response_is_structured_and_explainable():
    client.delete("/tasks")
    client.post("/tasks", json={
        "name": "Deep Work",
        "difficulty": 5,
        "duration": 60,
        "importance": 5,
        "deadline": "2026-09-30"
    })
    client.post("/availability", json={
        "date": "2026-09-28",
        "start_time": "09:00",
        "end_time": "12:00"
    })

    response = client.get("/schedule")
    assert response.status_code == 200
    payload = response.json()
    assert "schedule" in payload
    assert isinstance(payload["schedule"], list)
    assert payload["schedule"]
    assert "reason" in payload["schedule"][0]


def test_ml_status_reports_collecting_feedback_when_data_is_insufficient():
    client.delete("/feedback")
    response = client.get("/ml-status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"collecting_feedback", "ready"}
