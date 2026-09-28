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


def test_schedule_does_not_overlap_tasks_in_same_availability_window():
    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    client.post("/tasks", json={
        "name": "Task One",
        "difficulty": 3,
        "duration": 60,
        "importance": 5,
        "deadline": "2026-09-30"
    })
    client.post("/tasks", json={
        "name": "Task Two",
        "difficulty": 3,
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
    scheduled = [item for item in response.json()["schedule"] if item.get("type") == "task"]

    assert len(scheduled) >= 2
    intervals = [(item["start_minute"], item["end_minute"]) for item in scheduled]
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            first_start, first_end = intervals[i]
            second_start, second_end = intervals[j]
            assert first_end <= second_start or second_end <= first_start
