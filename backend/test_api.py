from datetime import date, timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from main import app
from services import state as state_module

client = TestClient(app)


@pytest.fixture(autouse=True)
def use_temp_sqlite_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_dayplan.db"
    monkeypatch.setenv("DAYPLAN_DB_PATH", str(test_db))
    state_module.init_state(test_db)
    yield


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
    client.delete("/availability")
    client.post("/tasks", json={
        "name": "Deep Work",
        "difficulty": 5,
        "duration": 60,
        "importance": 5,
        "deadline": date.today().isoformat()
    })
    client.post("/availability", json={
        "date": date.today().isoformat(),
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
        "deadline": date.today().isoformat()
    })
    client.post("/tasks", json={
        "name": "Task Two",
        "difficulty": 3,
        "duration": 60,
        "importance": 5,
        "deadline": date.today().isoformat()
    })
    client.post("/availability", json={
        "date": date.today().isoformat(),
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


def test_schedule_uses_multiple_windows_and_respects_configured_cutoff():
    today = date.today().isoformat()
    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")
    client.put("/settings", json={"end_of_day": "20:30"})

    for name in ("Morning task", "Afternoon task"):
        client.post("/tasks", json={
            "name": name,
            "difficulty": 3,
            "duration": 60,
            "importance": 4,
            "deadline": today,
        })
    windows = [
        {"date": today, "start_time": "09:00", "end_time": "10:00"},
        {"date": today, "start_time": "14:00", "end_time": "15:00"},
    ]
    for window in windows:
        client.post("/availability", json=window)

    response = client.get("/schedule")
    assert response.status_code == 200
    schedule = response.json()
    slots = [entry for entry in schedule["schedule"] if entry["type"] == "task"]
    assert {entry["start_time"] for entry in slots} == {"09:00", "14:00"}
    assert all(entry["duration"] <= 15 for entry in schedule["schedule"] if entry["type"] == "break")
    assert schedule["end_of_day"] == "20:30"

    removed = client.delete("/availability/window", params=windows[0])
    assert removed.status_code == 200
    assert len(client.get("/availability").json()) == 1

    client.delete("/tasks")
    client.delete("/availability")
    client.put("/settings", json={"end_of_day": "22:00"})
    client.post("/tasks", json={
        "name": "Late task",
        "difficulty": 3,
        "duration": 90,
        "importance": 5,
        "deadline": today,
    })
    client.post("/availability", json={
        "date": today,
        "start_time": "21:00",
        "end_time": "23:00",
    })

    cutoff_schedule = client.get("/schedule").json()
    assert not any(
        entry.get("type") == "task" and entry["end_time"] > "22:00"
        for entry in cutoff_schedule["schedule"]
    )
    assert cutoff_schedule["unscheduled_count"] == 1
    assert client.put("/settings", json={"end_of_day": "16:00"}).status_code == 422


def test_tasks_are_reported_unscheduled_when_no_availability_exists():
    client.delete("/tasks")
    client.delete("/availability")
    client.post("/tasks", json={
        "name": "Needs a window",
        "difficulty": 2,
        "duration": 30,
        "importance": 3,
    })

    schedule = client.get("/schedule").json()
    assert schedule["unscheduled_count"] == 1
    assert schedule["schedule"][0]["type"] == "unscheduled"
    assert schedule["schedule"][0]["task"] == "Needs a window"


def test_rich_feedback_is_stored_and_legacy_fields_remain_available():
    client.delete("/feedback")
    response = client.post("/feedback", json={
        "task_name": "Feedback test",
        "energy": 4,
        "difficulty": 3,
        "duration": 45,
        "completed": False,
        "completion_status": "partial",
        "difficulty_feedback": "about_right",
        "timing_feedback": "good_time",
        "energy_impact": "energized",
    })
    assert response.status_code == 200
    stored = client.get("/feedback").json()[0]
    assert stored["completed"] is False
    assert stored["completion_status"] == "partial"
    assert stored["difficulty_feedback"] == "about_right"
    assert stored["timing_feedback"] == "good_time"
    assert stored["energy_impact"] == "energized"
    assert stored["rating"] is None

    legacy = client.post("/feedback", json={
        "task_name": "Legacy feedback",
        "energy": 3,
        "difficulty": 2,
        "duration": 30,
        "completed": True,
        "on_time": True,
        "rating": 4,
    })
    assert legacy.status_code == 200
    assert client.get("/feedback").json()[1]["rating"] == 4


def test_three_hour_task_scheduled_tomorrow_when_today_is_one_hour():
    today = date.today()
    tomorrow = today + timedelta(days=1)

    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    client.post("/tasks", json={
        "name": "3-Hour Deep Project",
        "difficulty": 4,
        "duration": 180,
        "importance": 5,
    })

    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "09:00",
        "end_time": "10:00",
    })
    client.post("/availability", json={
        "date": tomorrow.isoformat(),
        "start_time": "12:00",
        "end_time": "16:00",
    })

    response = client.get("/schedule")
    assert response.status_code == 200
    payload = response.json()

    # Today's plan has no scheduled task
    today_tasks = [item for item in payload["schedule"] if item.get("type") == "task"]
    assert len(today_tasks) == 0

    # Tomorrow's plan has the task scheduled
    tomorrow_response = client.get(f"/schedule?date={tomorrow.isoformat()}")
    assert tomorrow_response.status_code == 200
    tomorrow_payload = tomorrow_response.json()
    tomorrow_tasks = [item for item in tomorrow_payload["schedule"] if item.get("type") == "task"]
    assert len(tomorrow_tasks) == 1
    assert tomorrow_tasks[0]["task"] == "3-Hour Deep Project"
    assert tomorrow_tasks[0]["start_time"] == "12:00"
    assert tomorrow_tasks[0]["end_time"] == "15:00"

    # Days array in payload has the task on day 1 (tomorrow)
    days = payload["days"]
    assert len(days) == 7
    assert len([t for t in days[1]["schedule"] if t.get("type") == "task"]) == 1


def test_task_with_deadline_today_never_moved_to_tomorrow():
    today = date.today()
    tomorrow = today + timedelta(days=1)

    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    client.post("/tasks", json={
        "name": "Urgent Due Today",
        "difficulty": 3,
        "duration": 180,
        "importance": 5,
        "deadline": today.isoformat(),
    })

    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "09:00",
        "end_time": "10:00",
    })
    client.post("/availability", json={
        "date": tomorrow.isoformat(),
        "start_time": "12:00",
        "end_time": "16:00",
    })

    response = client.get("/schedule")
    assert response.status_code == 200
    payload = response.json()

    # Must NOT be moved to tomorrow
    tomorrow_response = client.get(f"/schedule?date={tomorrow.isoformat()}")
    assert tomorrow_response.status_code == 200
    tomorrow_payload = tomorrow_response.json()
    tomorrow_tasks = [item for item in tomorrow_payload["schedule"] if item.get("type") == "task"]
    assert len(tomorrow_tasks) == 0

    # Must be reported unscheduled on today with clear deadline reason
    today_unscheduled = [item for item in payload["schedule"] if item.get("type") == "unscheduled"]
    assert len(today_unscheduled) == 1
    assert today_unscheduled[0]["task"] == "Urgent Due Today"
    assert "deadline prevents scheduling on future dates" in today_unscheduled[0]["reason"].lower()


def test_task_scheduled_at_most_once_across_seven_day_horizon():
    today = date.today()

    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    for i in range(5):
        client.post("/tasks", json={
            "name": f"Task {i + 1}",
            "difficulty": 3,
            "duration": 60,
            "importance": 4,
        })

    for i in range(7):
        d = today + timedelta(days=i)
        client.post("/availability", json={
            "date": d.isoformat(),
            "start_time": "09:00",
            "end_time": "11:00",
        })

    response = client.get("/schedule")
    assert response.status_code == 200
    payload = response.json()

    all_scheduled_task_ids = []
    for day in payload["days"]:
        for item in day["schedule"]:
            if item.get("type") == "task":
                all_scheduled_task_ids.append(item["task_id"])

    # Ensure every task ID appears at most once across all 7 days
    assert len(all_scheduled_task_ids) == len(set(all_scheduled_task_ids))


def test_tasks_respect_availability_deadlines_cutoff_and_non_overlap():
    today = date.today()
    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")
    client.put("/settings", json={"end_of_day": "21:00"})

    # Busy block on day 1 from 13:00 to 14:00
    d1 = today + timedelta(days=1)
    client.post("/time-blocks", json={
        "date": d1.isoformat(),
        "start_time": "13:00",
        "end_time": "14:00",
        "type": "busy",
    })

    client.post("/availability", json={
        "date": d1.isoformat(),
        "start_time": "12:00",
        "end_time": "16:00",
    })

    # Task 1: 60 mins, deadline day 1
    client.post("/tasks", json={
        "name": "Day 1 Task A",
        "difficulty": 3,
        "duration": 60,
        "importance": 5,
        "deadline": d1.isoformat(),
    })
    # Task 2: 60 mins, deadline day 1
    client.post("/tasks", json={
        "name": "Day 1 Task B",
        "difficulty": 3,
        "duration": 60,
        "importance": 4,
        "deadline": d1.isoformat(),
    })

    response = client.get(f"/schedule?date={d1.isoformat()}")
    assert response.status_code == 200
    d1_schedule = response.json()

    scheduled = [item for item in d1_schedule["schedule"] if item.get("type") == "task"]
    assert len(scheduled) == 2

    # Check non-overlap and busy block avoidance (13:00-14:00 is busy)
    for t in scheduled:
        assert t["start_time"] >= "12:00"
        assert t["end_time"] <= "21:00"
        assert not (t["start_time"] < "14:00" and t["end_time"] > "13:00")

    intervals = [(t["start_minute"], t["end_minute"]) for t in scheduled]
    assert intervals[0][1] <= intervals[1][0] or intervals[1][1] <= intervals[0][0]


def test_duplicate_or_overlapping_availability_windows_do_not_inflate_available_minutes():
    today = date.today()
    tomorrow = today + timedelta(days=1)

    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    # Attempt to post duplicate windows
    res1 = client.post("/availability", json={
        "date": tomorrow.isoformat(),
        "start_time": "12:00",
        "end_time": "16:00",
    })
    assert res1.status_code == 200
    assert res1.json()["message"] == "Availability window added successfully"

    res2 = client.post("/availability", json={
        "date": tomorrow.isoformat(),
        "start_time": "12:00",
        "end_time": "16:00",
    })
    assert res2.status_code == 200
    assert "already exists" in res2.json()["message"]

    # Overlapping window: 14:00 to 18:00 extends 12:00-16:00 to 12:00-18:00 (6 hours = 360 mins)
    res3 = client.post("/availability", json={
        "date": tomorrow.isoformat(),
        "start_time": "14:00",
        "end_time": "18:00",
    })
    assert res3.status_code == 200

    # Ensure get_availability has only unique windows
    avail_list = client.get("/availability").json()
    assert len(avail_list) == 2

    # Verify available minutes calculation: 12:00 to 18:00 is 360 minutes
    schedule_res = client.get(f"/schedule?date={tomorrow.isoformat()}")
    assert schedule_res.status_code == 200
    schedule_data = schedule_res.json()
    assert schedule_data["available_minutes"] == 360
    assert schedule_data["available_minutes"] == schedule_data["scheduled_minutes"] + schedule_data["unused_minutes"]


def test_task_only_fitting_on_day_eight_remains_unscheduled_with_clear_explanation():
    today = date.today()
    day_eight = today + timedelta(days=7)  # 8th calendar day

    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    client.post("/tasks", json={
        "name": "Big Project",
        "difficulty": 4,
        "duration": 180,
        "importance": 5,
    })

    # Only available on day eight
    client.post("/availability", json={
        "date": day_eight.isoformat(),
        "start_time": "12:00",
        "end_time": "16:00",
    })

    response = client.get("/schedule")
    assert response.status_code == 200
    payload = response.json()

    assert len(payload["days"]) == 7
    assert payload["days"][-1]["date"] != day_eight.isoformat()

    # The task must be unscheduled
    assert payload["unscheduled_count"] == 1
    unscheduled_item = payload["schedule"][0]
    assert unscheduled_item["type"] == "unscheduled"
    assert "seven-day" in unscheduled_item["reason"].lower()


def test_tasks_and_availability_outside_horizon_not_deleted_or_silently_changed():
    today = date.today()
    day_ten = today + timedelta(days=10)
    day_twenty = today + timedelta(days=20)

    client.delete("/tasks")
    client.delete("/availability")

    client.post("/tasks", json={
        "name": "Far Future Task",
        "difficulty": 2,
        "duration": 60,
        "importance": 3,
        "deadline": day_twenty.isoformat(),
    })
    client.post("/availability", json={
        "date": day_ten.isoformat(),
        "start_time": "10:00",
        "end_time": "12:00",
    })

    client.get("/schedule")

    # Neither the task nor the availability window was deleted
    tasks = client.get("/tasks").json()
    assert any(t["name"] == "Far Future Task" for t in tasks)

    avail = client.get("/availability").json()
    assert any(w["date"] == day_ten.isoformat() for w in avail)


def test_selecting_date_shows_actual_schedule_and_statistics():
    today = date.today()
    day_three = today + timedelta(days=3)

    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    # Add task for day 3
    client.post("/tasks", json={
        "name": "Midweek Review",
        "difficulty": 3,
        "duration": 90,
        "importance": 4,
    })

    # Availability only on day 3
    client.post("/availability", json={
        "date": day_three.isoformat(),
        "start_time": "10:00",
        "end_time": "13:00",
    })

    # Today's view
    today_res = client.get("/schedule")
    assert today_res.status_code == 200
    today_data = today_res.json()
    assert today_data["date"] == today.isoformat()
    assert today_data["available_minutes"] == 0
    assert today_data["scheduled_minutes"] == 0
    assert today_data["unused_minutes"] == 0
    assert len(today_data["days"]) == 7

    # Day 3 view
    day3_res = client.get(f"/schedule?date={day_three.isoformat()}")
    assert day3_res.status_code == 200
    day3_data = day3_res.json()
    assert day3_data["date"] == day_three.isoformat()
    assert day3_data["available_minutes"] == 180
    assert day3_data["scheduled_minutes"] == 90
    assert day3_data["unused_minutes"] == 90
    assert day3_data["available_minutes"] == day3_data["scheduled_minutes"] + day3_data["unused_minutes"]
    tasks_on_day3 = [item for item in day3_data["schedule"] if item.get("type") == "task"]
    assert len(tasks_on_day3) == 1
    assert tasks_on_day3[0]["task"] == "Midweek Review"


def test_reschedule_valid_move_updates_schedule_and_persists():
    today = date.today()
    tomorrow = today + timedelta(days=1)

    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    # Add 60-min task
    t_res = client.post("/tasks", json={
        "name": "Moveable Task",
        "difficulty": 3,
        "duration": 60,
        "importance": 4,
    })
    task_id = t_res.json()["task"]["id"]

    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "09:00",
        "end_time": "12:00",
    })
    client.post("/availability", json={
        "date": tomorrow.isoformat(),
        "start_time": "14:00",
        "end_time": "17:00",
    })

    # Reschedule task to tomorrow at 15:00
    reschedule_res = client.post(f"/tasks/{task_id}/reschedule", json={
        "date": tomorrow.isoformat(),
        "start_time": "15:00",
    })
    assert reschedule_res.status_code == 200
    assert reschedule_res.json()["date"] == tomorrow.isoformat()
    assert reschedule_res.json()["start_time"] == "15:00"
    assert reschedule_res.json()["end_time"] == "16:00"

    # Regenerate schedule and verify persistence
    schedule_res = client.get(f"/schedule?date={tomorrow.isoformat()}")
    assert schedule_res.status_code == 200
    sched = schedule_res.json()
    tomorrow_tasks = [t for t in sched["schedule"] if t.get("type") == "task"]
    assert len(tomorrow_tasks) == 1
    assert tomorrow_tasks[0]["task_id"] == task_id
    assert tomorrow_tasks[0]["start_time"] == "15:00"
    assert tomorrow_tasks[0]["end_time"] == "16:00"


def test_reschedule_rejects_outside_horizon():
    today = date.today()
    day_eight = today + timedelta(days=7)

    client.delete("/tasks")
    client.delete("/availability")

    t_res = client.post("/tasks", json={
        "name": "Horizon Bound",
        "difficulty": 3,
        "duration": 60,
        "importance": 4,
    })
    task_id = t_res.json()["task"]["id"]

    res = client.post(f"/tasks/{task_id}/reschedule", json={
        "date": day_eight.isoformat(),
        "start_time": "10:00",
    })
    assert res.status_code == 400
    assert "outside the strict seven-day planning horizon" in res.json()["detail"].lower()


def test_reschedule_rejects_deadline_violation():
    today = date.today()
    tomorrow = today + timedelta(days=1)
    day_three = today + timedelta(days=3)

    client.delete("/tasks")
    client.delete("/availability")

    t_res = client.post("/tasks", json={
        "name": "Due Tomorrow",
        "difficulty": 3,
        "duration": 60,
        "importance": 4,
        "deadline": tomorrow.isoformat(),
    })
    task_id = t_res.json()["task"]["id"]

    client.post("/availability", json={
        "date": day_three.isoformat(),
        "start_time": "10:00",
        "end_time": "12:00",
    })

    res = client.post(f"/tasks/{task_id}/reschedule", json={
        "date": day_three.isoformat(),
        "start_time": "10:00",
    })
    assert res.status_code == 400
    assert "after its deadline" in res.json()["detail"].lower()


def test_reschedule_rejects_cutoff_violation():
    today = date.today()

    client.delete("/tasks")
    client.delete("/availability")
    client.put("/settings", json={"end_of_day": "21:00"})

    t_res = client.post("/tasks", json={
        "name": "Late Evening Task",
        "difficulty": 3,
        "duration": 90,
        "importance": 4,
    })
    task_id = t_res.json()["task"]["id"]

    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "20:00",
        "end_time": "22:00",
    })

    res = client.post(f"/tasks/{task_id}/reschedule", json={
        "date": today.isoformat(),
        "start_time": "20:00",
    })
    assert res.status_code == 400
    assert "exceeds the 21:00 cutoff" in res.json()["detail"].lower()


def test_reschedule_rejects_overlap_and_rollback_preserves_position():
    today = date.today()

    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    t1_res = client.post("/tasks", json={
        "name": "Existing Task",
        "difficulty": 3,
        "duration": 60,
        "importance": 5,
    })
    t1_id = t1_res.json()["task"]["id"]

    t2_res = client.post("/tasks", json={
        "name": "Conflicting Task",
        "difficulty": 3,
        "duration": 60,
        "importance": 3,
    })
    t2_id = t2_res.json()["task"]["id"]

    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "10:00",
        "end_time": "13:00",
    })

    # Place t1 at 10:00 - 11:00
    client.post(f"/tasks/{t1_id}/reschedule", json={
        "date": today.isoformat(),
        "start_time": "10:00",
    })

    # Attempt to place t2 overlapping with t1 (10:30 - 11:30)
    conflict_res = client.post(f"/tasks/{t2_id}/reschedule", json={
        "date": today.isoformat(),
        "start_time": "10:30",
    })
    assert conflict_res.status_code == 400
    assert "overlaps with task 'Existing Task'" in conflict_res.json()["detail"]

    # Verify rollback/preservation: t1 is still at 10:00, t2 was placed in available space or unscheduled
    sched = client.get("/schedule").json()
    t1_entry = next(item for item in sched["schedule"] if item.get("task_id") == t1_id)
    assert t1_entry["start_time"] == "10:00"
    assert t1_entry["end_time"] == "11:00"


def test_tasks_survive_reinitialization():
    today = date.today()
    client.delete("/tasks")
    r1 = client.post("/tasks", json={
        "name": "Persistent Task 1",
        "difficulty": 4,
        "duration": 45,
        "importance": 5,
        "deadline": (today + timedelta(days=2)).isoformat(),
    })
    assert r1.status_code == 200
    t1_id = r1.json()["task"]["id"]

    r2 = client.post("/tasks", json={
        "name": "Persistent Task 2",
        "difficulty": 2,
        "duration": 90,
        "importance": 3,
    })
    assert r2.status_code == 200
    t2_id = r2.json()["task"]["id"]

    # Reinitialize state from the active DB path
    state_module.init_state(state_module.active_db_path)

    tasks_res = client.get("/tasks")
    assert tasks_res.status_code == 200
    tasks = tasks_res.json()
    assert len(tasks) == 2
    task1 = next(t for t in tasks if t["id"] == t1_id)
    assert task1["name"] == "Persistent Task 1"
    assert task1["difficulty"] == 4
    assert task1["duration"] == 45
    assert task1["importance"] == 5
    assert task1["deadline"] == (today + timedelta(days=2)).isoformat()

    task2 = next(t for t in tasks if t["id"] == t2_id)
    assert task2["name"] == "Persistent Task 2"
    assert task2["difficulty"] == 2
    assert task2["duration"] == 90
    assert task2["deadline"] is None


def test_availability_windows_survive_reinitialization_without_duplication():
    today = date.today()
    client.delete("/availability")

    # Add window
    r1 = client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "09:00",
        "end_time": "12:00",
    })
    assert r1.status_code == 200
    assert r1.json()["message"] == "Availability window added successfully"

    # Repeated identical call should not duplicate
    r2 = client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "09:00",
        "end_time": "12:00",
    })
    assert r2.status_code == 200
    assert r2.json()["message"] == "Availability window already exists"

    # Add second distinct window
    r3 = client.post("/availability", json={
        "date": (today + timedelta(days=1)).isoformat(),
        "start_time": "14:00",
        "end_time": "17:00",
    })
    assert r3.status_code == 200

    # Reinitialize state
    state_module.init_state(state_module.active_db_path)

    avail_res = client.get("/availability")
    assert avail_res.status_code == 200
    windows = avail_res.json()
    assert len(windows) == 2
    dates = [w["date"] for w in windows]
    assert today.isoformat() in dates
    assert (today + timedelta(days=1)).isoformat() in dates


def test_manual_calendar_placements_survive_reinitialization_and_regeneration():
    today = date.today()
    client.delete("/tasks")
    client.delete("/availability")

    t_res = client.post("/tasks", json={
        "name": "Manually Placed Task",
        "difficulty": 3,
        "duration": 60,
        "importance": 4,
    })
    task_id = t_res.json()["task"]["id"]

    client.post("/availability", json={
        "date": (today + timedelta(days=1)).isoformat(),
        "start_time": "13:00",
        "end_time": "16:00",
    })

    # Reschedule via Calendar endpoint
    res = client.post(f"/tasks/{task_id}/reschedule", json={
        "date": (today + timedelta(days=1)).isoformat(),
        "start_time": "14:00",
    })
    assert res.status_code == 200
    assert res.json()["start_time"] == "14:00"

    # Reinitialize backend state
    state_module.init_state(state_module.active_db_path)

    # Verify manual placement survived in memory & DB
    assert task_id in state_module.manual_placements
    assert str(state_module.manual_placements[task_id]["date"]) == (today + timedelta(days=1)).isoformat()
    assert state_module.manual_placements[task_id]["start_time"] == "14:00"

    # Verify schedule regeneration preserves the manual placement
    sched = client.get(f"/schedule?date={(today + timedelta(days=1)).isoformat()}").json()
    day_entry = next(d for d in sched["days"] if d["date"] == (today + timedelta(days=1)).isoformat())
    task_slot = next(item for item in day_entry["schedule"] if item.get("task_id") == task_id)
    assert task_slot["start_time"] == "14:00"
    assert task_slot["end_time"] == "15:00"
    assert task_slot.get("is_manual") is True


def test_feedback_and_settings_restored_correctly():
    client.delete("/feedback")

    client.put("/settings", json={"end_of_day": "23:00"})
    client.post("/energy", json={"level": 5})

    client.post("/wearable-data", json={
        "sleep_hours": 7.5,
        "resting_heart_rate": 60,
        "hrv": 55.0,
        "steps": 9000,
        "active_minutes": 45,
    })

    client.post("/feedback", json={
        "task_name": "Review Code",
        "task_id": 1,
        "energy": 4,
        "difficulty": 3,
        "duration": 60,
        "completed": True,
        "on_time": True,
        "rating": 5,
        "completion_status": "completed",
        "difficulty_feedback": "about_right",
        "timing_feedback": "good_time",
        "energy_impact": "energized",
    })

    # Reinitialize state
    state_module.init_state(state_module.active_db_path)

    settings_res = client.get("/settings").json()
    assert settings_res["end_of_day"] == "23:00"

    energy_res = client.get("/energy").json()
    assert energy_res["energy"] == 5

    wearable_res = client.get("/wearable-data").json()
    assert wearable_res["sleep_hours"] == 7.5
    assert wearable_res["steps"] == 9000

    feedback_res = client.get("/feedback").json()
    assert len(feedback_res) == 1
    fb = feedback_res[0]
    assert fb["task_name"] == "Review Code"
    assert fb["rating"] == 5
    assert fb["completion_status"] == "completed"
    assert fb["energy_impact"] == "energized"


def test_deleting_task_cleans_up_associated_state():
    today = date.today()
    client.delete("/tasks")
    client.delete("/availability")

    t_res = client.post("/tasks", json={
        "name": "Task to Delete",
        "difficulty": 3,
        "duration": 60,
        "importance": 4,
    })
    task_id = t_res.json()["task"]["id"]

    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "10:00",
        "end_time": "12:00",
    })

    client.post(f"/tasks/{task_id}/reschedule", json={
        "date": today.isoformat(),
        "start_time": "10:00",
    })
    assert task_id in state_module.manual_placements

    # Delete task
    del_res = client.delete(f"/tasks/{task_id}")
    assert del_res.status_code == 200
    assert task_id not in state_module.manual_placements

    # Reinitialize state and verify neither task nor manual placement exist
    state_module.init_state(state_module.active_db_path)
    assert not any(t.id == task_id for t in state_module.tasks)
    assert task_id not in state_module.manual_placements


def test_database_errors_do_not_falsely_report_success(monkeypatch):
    import sqlite3

    def failing_add_task(*args, **kwargs):
        raise sqlite3.OperationalError("Simulated database failure")

    monkeypatch.setattr("services.db.add_task", failing_add_task)

    initial_tasks_count = len(state_module.tasks)
    response = client.post("/tasks", json={
        "name": "Failed Task",
        "difficulty": 3,
        "duration": 30,
        "importance": 3,
    })
    assert response.status_code == 500
    assert "Database error" in response.json()["detail"]
    assert len(state_module.tasks) == initial_tasks_count


def test_weekly_availability_creates_expected_windows_within_horizon():
    today = date.today()
    client.delete("/availability")

    horizon_dates = [today + timedelta(days=i) for i in range(7)]
    target_weekdays = ["Monday", "Wednesday"]
    expected_dates = [d for d in horizon_dates if d.strftime("%A") in target_weekdays]

    res = client.post("/availability/weekly", json={
        "weekdays": target_weekdays,
        "start_time": "09:00",
        "end_time": "11:00",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["total_created"] == len(expected_dates)
    assert data["total_skipped"] == 0

    avail = client.get("/availability").json()
    assert len(avail) == len(expected_dates)
    for exp_date in expected_dates:
        assert any(w["date"] == exp_date.isoformat() and w["start_time"] == "09:00" and w["end_time"] == "11:00" for w in avail)


def test_weekly_availability_never_affects_eighth_day():
    today = date.today()
    client.delete("/availability")

    # Select all 7 weekdays
    res = client.post("/availability/weekly", json={
        "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "start_time": "10:00",
        "end_time": "12:00",
    })
    assert res.status_code == 200
    data = res.json()

    # Must create exactly 7 windows (for today through day 7)
    assert data["total_created"] == 7

    day_eight = today + timedelta(days=7)
    avail = client.get("/availability").json()
    # Ensure no window exists on day eight or beyond
    assert not any(w["date"] == day_eight.isoformat() for w in avail)
    assert not any(w["date"] > (today + timedelta(days=6)).isoformat() for w in avail)


def test_weekly_availability_repeated_submission_no_duplicates():
    today = date.today()
    client.delete("/availability")

    payload = {
        "weekdays": ["Tuesday", "Thursday"],
        "start_time": "14:00",
        "end_time": "16:00",
    }
    r1 = client.post("/availability/weekly", json=payload)
    assert r1.status_code == 200
    created_count = r1.json()["total_created"]
    assert created_count > 0

    # Repeated identical submission
    r2 = client.post("/availability/weekly", json=payload)
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["total_created"] == 0
    assert data2["total_skipped"] == created_count
    assert len(data2["skipped"]) == created_count

    # Total in db/memory must remain created_count
    avail = client.get("/availability").json()
    assert len(avail) == created_count


def test_weekly_availability_rejects_invalid_time_ranges():
    # End time before start time
    r1 = client.post("/availability/weekly", json={
        "weekdays": ["Monday"],
        "start_time": "15:00",
        "end_time": "12:00",
    })
    assert r1.status_code == 400
    assert "End time must be after start time" in r1.json()["detail"]

    # End time equal to start time
    r2 = client.post("/availability/weekly", json={
        "weekdays": ["Monday"],
        "start_time": "12:00",
        "end_time": "12:00",
    })
    assert r2.status_code == 400

    # Empty weekdays
    r3 = client.post("/availability/weekly", json={
        "weekdays": [],
        "start_time": "09:00",
        "end_time": "12:00",
    })
    assert r3.status_code == 422  # pydantic min_length validation

    # Invalid time string format
    r4 = client.post("/availability/weekly", json={
        "weekdays": ["Monday"],
        "start_time": "invalid",
        "end_time": "12:00",
    })
    assert r4.status_code == 400


def test_weekly_availability_preserves_existing_availability():
    today = date.today()
    client.delete("/availability")

    # Add a custom individual window
    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "07:00",
        "end_time": "09:00",
    })

    # Add weekly availability
    res = client.post("/availability/weekly", json={
        "weekdays": [today.strftime("%A")],
        "start_time": "13:00",
        "end_time": "16:00",
    })
    assert res.status_code == 200

    avail = client.get("/availability").json()
    # Both windows must be present
    today_windows = [w for w in avail if w["date"] == today.isoformat()]
    assert len(today_windows) == 2
    times = [(w["start_time"], w["end_time"]) for w in today_windows]
    assert ("07:00", "09:00") in times
    assert ("13:00", "16:00") in times


def test_weekly_availability_overlapping_does_not_inflate_minutes():
    today = date.today()
    client.delete("/availability")

    # Window 1: 10:00 to 12:00 (120 minutes)
    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "10:00",
        "end_time": "12:00",
    })

    # Window 2 overlapping via weekly: 11:00 to 13:00 (120 minutes)
    client.post("/availability/weekly", json={
        "weekdays": [today.strftime("%A")],
        "start_time": "11:00",
        "end_time": "13:00",
    })

    avail = client.get("/availability").json()
    assert len(avail) == 2

    # Check schedule available minutes: union is 10:00 to 13:00 = 180 min, NOT 240 min
    sched = client.get(f"/schedule?date={today.isoformat()}").json()
    assert sched["available_minutes"] == 180


def test_weekly_availability_survives_backend_reinitialization():
    today = date.today()
    client.delete("/availability")

    res = client.post("/availability/weekly", json={
        "weekdays": ["Monday", "Friday"],
        "start_time": "08:00",
        "end_time": "10:00",
    })
    created_count = res.json()["total_created"]

    # Reinitialize state
    state_module.init_state(state_module.active_db_path)

    avail = client.get("/availability").json()
    assert len(avail) == created_count
    for w in avail:
        assert w["start_time"] == "08:00"
        assert w["end_time"] == "10:00"


def test_planner_and_calendar_reflect_same_availability():
    today = date.today()
    client.delete("/availability")

    client.post("/availability/weekly", json={
        "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "start_time": "09:00",
        "end_time": "12:00",
    })

    sched = client.get("/schedule").json()
    all_avail = client.get("/availability").json()

    # The 7 days in sched['days'] (Calendar time-grid) and weekly overview must match all_avail
    for day in sched["days"]:
        day_date = day["date"]
        matching_avail = [w for w in all_avail if w["date"] == day_date]
        if matching_avail:
            assert day["available_minutes"] == 180
        else:
            assert day["available_minutes"] == 0


def test_weekly_availability_database_error_handling(monkeypatch):
    import sqlite3

    client.delete("/availability")

    def failing_batch(*args, **kwargs):
        raise sqlite3.OperationalError("Database disk error")

    monkeypatch.setattr("services.db.add_availability_batch", failing_batch)

    initial_len = len(state_module.availability_windows)
    res = client.post("/availability/weekly", json={
        "weekdays": ["Monday", "Tuesday"],
        "start_time": "09:00",
        "end_time": "11:00",
    })
    assert res.status_code == 500
    assert "Database error" in res.json()["detail"]
    assert len(state_module.availability_windows) == initial_len


def test_high_energy_makes_demanding_tasks_preferable_when_constraints_permit():
    today = date.today()
    tomorrow = today + timedelta(days=1)
    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    # Set user energy to 5 (high)
    client.post("/energy", json={"level": 5})

    # Task A: Demanding (difficulty 5, duration 60, importance 3)
    r1 = client.post("/tasks", json={
        "name": "Demanding Task",
        "difficulty": 5,
        "duration": 60,
        "importance": 3,
    })
    t1_id = r1.json()["task"]["id"]

    # Task B: Lighter (difficulty 1, duration 60, importance 3)
    r2 = client.post("/tasks", json={
        "name": "Lighter Task",
        "difficulty": 1,
        "duration": 60,
        "importance": 3,
    })
    t2_id = r2.json()["task"]["id"]

    # Availability: 1 hour today, 1 hour tomorrow
    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "09:00",
        "end_time": "10:00",
    })
    client.post("/availability", json={
        "date": tomorrow.isoformat(),
        "start_time": "09:00",
        "end_time": "10:00",
    })

    sched = client.get("/schedule").json()
    today_tasks = [t for t in sched["schedule"] if t.get("type") == "task"]
    assert len(today_tasks) == 1
    assert today_tasks[0]["task_id"] == t1_id
    assert today_tasks[0]["task"] == "Demanding Task"
    assert "energy level of 5/5" in today_tasks[0]["explanation"]
    assert "difficulty 5/5" in today_tasks[0]["explanation"] or "difficulty of 5/5" in today_tasks[0]["explanation"]

    tomorrow_sched = client.get(f"/schedule?date={tomorrow.isoformat()}").json()
    tomorrow_tasks = [t for t in tomorrow_sched["schedule"] if t.get("type") == "task"]
    assert len(tomorrow_tasks) == 1
    assert tomorrow_tasks[0]["task_id"] == t2_id


def test_low_energy_favors_less_demanding_tasks_where_feasible():
    today = date.today()
    tomorrow = today + timedelta(days=1)
    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    # Set user energy to 1 (low)
    client.post("/energy", json={"level": 1})

    # Task A: Demanding (difficulty 5, duration 60, importance 3)
    r1 = client.post("/tasks", json={
        "name": "Demanding Task",
        "difficulty": 5,
        "duration": 60,
        "importance": 3,
    })
    t1_id = r1.json()["task"]["id"]

    # Task B: Lighter (difficulty 1, duration 60, importance 3)
    r2 = client.post("/tasks", json={
        "name": "Lighter Task",
        "difficulty": 1,
        "duration": 60,
        "importance": 3,
    })
    t2_id = r2.json()["task"]["id"]

    # Availability: 1 hour today, 1 hour tomorrow
    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "09:00",
        "end_time": "10:00",
    })
    client.post("/availability", json={
        "date": tomorrow.isoformat(),
        "start_time": "09:00",
        "end_time": "10:00",
    })

    sched = client.get("/schedule").json()
    today_tasks = [t for t in sched["schedule"] if t.get("type") == "task"]
    assert len(today_tasks) == 1
    assert today_tasks[0]["task_id"] == t2_id
    assert today_tasks[0]["task"] == "Lighter Task"
    assert "energy level of 1/5" in today_tasks[0]["explanation"]
    assert "difficulty 1/5" in today_tasks[0]["explanation"] or "difficulty of 1/5" in today_tasks[0]["explanation"]

    tomorrow_sched = client.get(f"/schedule?date={tomorrow.isoformat()}").json()
    tomorrow_tasks = [t for t in tomorrow_sched["schedule"] if t.get("type") == "task"]
    assert len(tomorrow_tasks) == 1
    assert tomorrow_tasks[0]["task_id"] == t1_id


def test_urgent_deadlines_and_hard_constraints_never_violated_for_energy_matching():
    today = date.today()
    tomorrow = today + timedelta(days=1)
    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    # Set user energy to 1 (low)
    client.post("/energy", json={"level": 1})

    # Demanding task with deadline TODAY
    r1 = client.post("/tasks", json={
        "name": "Urgent Hard Task",
        "difficulty": 5,
        "duration": 60,
        "importance": 3,
        "deadline": today.isoformat(),
    })
    t1_id = r1.json()["task"]["id"]

    # Easy non-urgent task with deadline in 3 days
    r2 = client.post("/tasks", json={
        "name": "Non-urgent Easy Task",
        "difficulty": 1,
        "duration": 60,
        "importance": 3,
        "deadline": (today + timedelta(days=3)).isoformat(),
    })
    t2_id = r2.json()["task"]["id"]

    # Only 1 hour available today, 1 hour tomorrow
    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "09:00",
        "end_time": "10:00",
    })
    client.post("/availability", json={
        "date": tomorrow.isoformat(),
        "start_time": "09:00",
        "end_time": "10:00",
    })

    sched = client.get("/schedule").json()
    today_tasks = [t for t in sched["schedule"] if t.get("type") == "task"]
    assert len(today_tasks) == 1
    # Hard deadline must be honored even with low energy
    assert today_tasks[0]["task_id"] == t1_id
    assert today_tasks[0]["task"] == "Urgent Hard Task"
    assert "urgent" in today_tasks[0]["explanation"].lower()
    assert "due " + today.isoformat() in today_tasks[0]["explanation"].lower()


def test_future_dates_do_not_incorrectly_inherit_todays_energy_level():
    today = date.today()
    tomorrow = today + timedelta(days=1)
    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    # Set today's energy to 5
    client.post("/energy", json={"level": 5})

    client.post("/tasks", json={
        "name": "Tomorrow Project",
        "difficulty": 4,
        "duration": 60,
        "importance": 4,
    })

    # Available only on tomorrow
    client.post("/availability", json={
        "date": tomorrow.isoformat(),
        "start_time": "14:00",
        "end_time": "16:00",
    })

    sched = client.get(f"/schedule?date={tomorrow.isoformat()}").json()
    assert sched["readiness"] == "unknown"
    assert sched["energy"] is None

    tomorrow_day = next(d for d in sched["days"] if d["date"] == tomorrow.isoformat())
    assert tomorrow_day["readiness"] == "unknown"

    tomorrow_task = next(item for item in tomorrow_day["schedule"] if item.get("type") == "task")
    # Energy fit must be None for future date
    assert tomorrow_task["energy_fit"] is None
    # Explanation must state readiness is unknown, not claim optimal biological timing
    assert "energy readiness is unknown for future dates" in tomorrow_task["explanation"].lower()
    assert "5/5" not in tomorrow_task["explanation"]
    assert "optimal" not in tomorrow_task["explanation"].lower()


def test_explanations_reflect_actual_factors_and_values():
    today = date.today()
    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    # Set energy to 4
    client.post("/energy", json={"level": 4})

    client.post("/tasks", json={
        "name": "Architecture Review",
        "difficulty": 4,
        "duration": 60,
        "importance": 5,
        "deadline": (today + timedelta(days=2)).isoformat(),
    })

    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "12:00",
        "end_time": "14:00",
    })

    sched = client.get("/schedule").json()
    task_item = next(item for item in sched["schedule"] if item.get("type") == "task")

    expected_explanation = (
        "Scheduled at 12:00 because this was the earliest feasible slot, "
        "the task has high priority, and your reported energy level of 4/5 is compatible with its difficulty of 4/5."
    )
    assert task_item["explanation"] == expected_explanation


def test_manual_placements_are_identified_correctly():
    today = date.today()
    tomorrow = today + timedelta(days=1)
    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/time-blocks")

    t_res = client.post("/tasks", json={
        "name": "Manually Scheduled Task",
        "difficulty": 3,
        "duration": 60,
        "importance": 4,
    })
    task_id = t_res.json()["task"]["id"]

    client.post("/availability", json={
        "date": tomorrow.isoformat(),
        "start_time": "10:00",
        "end_time": "13:00",
    })

    # Reschedule manually
    res = client.post(f"/tasks/{task_id}/reschedule", json={
        "date": tomorrow.isoformat(),
        "start_time": "11:00",
    })
    assert res.status_code == 200

    sched = client.get(f"/schedule?date={tomorrow.isoformat()}").json()
    tomorrow_day = next(d for d in sched["days"] if d["date"] == tomorrow.isoformat())
    task_item = next(t for t in tomorrow_day["schedule"] if t.get("task_id") == task_id)

    assert task_item["is_manual"] is True
    assert "manually placed at 11:00" in task_item["explanation"].lower()
    assert "chosen manually by you" in task_item["explanation"].lower()
    assert "optimal" not in task_item["explanation"].lower()


def test_missing_feedback_activates_fallback_without_breaking():
    today = date.today()
    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/feedback")

    # Verify ml-status indicates collecting feedback
    ml_status = client.get("/ml-status").json()
    assert ml_status["status"] == "collecting_feedback"

    client.post("/tasks", json={
        "name": "No Feedback Task",
        "difficulty": 3,
        "duration": 60,
        "importance": 3,
    })
    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "09:00",
        "end_time": "11:00",
    })

    # Schedule should generate cleanly with fallback
    sched = client.get("/schedule").json()
    task_item = next(t for t in sched["schedule"] if t.get("type") == "task")
    assert task_item is not None
    # No personalization claimed in explanation
    assert "feedback personalization" not in task_item["explanation"].lower()
    assert "past feedback" not in task_item["explanation"].lower()

    # Now add sufficient feedback (4 entries with varying outcomes)
    for i, completed in enumerate([True, False, True, True]):
        client.post("/feedback", json={
            "task_name": f"Past Task {i}",
            "energy": 3 + (i % 2),
            "difficulty": 2 + (i % 3),
            "duration": 45,
            "completed": completed,
        })

    ml_status_after = client.get("/ml-status").json()
    assert ml_status_after["status"] == "ready"

    # Schedule generation continues to work seamlessly with trained model
    sched_after = client.get("/schedule").json()
    task_after = next(t for t in sched_after["schedule"] if t.get("type") == "task")
    assert task_after is not None


def test_calendar_trash_deletion_removes_task_and_manual_placement_persisting_across_reloads():
    today = date.today()
    tomorrow = today + timedelta(days=1)
    client.delete("/tasks")
    client.delete("/availability")
    client.delete("/feedback")

    # Setup availability for today and tomorrow
    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "09:00",
        "end_time": "12:00",
    })
    client.post("/availability", json={
        "date": tomorrow.isoformat(),
        "start_time": "10:00",
        "end_time": "14:00",
    })

    # Add historical feedback
    client.post("/feedback", json={
        "task_name": "Historical Task",
        "energy": 4,
        "difficulty": 3,
        "duration": 60,
        "completed": True,
    })

    # Add Task A and Task B
    res_a = client.post("/tasks", json={
        "name": "Task A to Delete",
        "difficulty": 3,
        "duration": 60,
        "importance": 4,
    })
    task_a_id = res_a.json()["task"]["id"]

    res_b = client.post("/tasks", json={
        "name": "Task B to Keep",
        "difficulty": 2,
        "duration": 45,
        "importance": 3,
    })
    task_b_id = res_b.json()["task"]["id"]

    # Manually place Task A on tomorrow
    res_place = client.post(f"/tasks/{task_a_id}/reschedule", json={
        "date": tomorrow.isoformat(),
        "start_time": "10:00",
    })
    assert res_place.status_code == 200
    assert task_a_id in state_module.manual_placements

    # Confirm schedule has Task A on tomorrow and Task B placed
    sched_before = client.get("/schedule").json()
    tomorrow_day = next(d for d in sched_before["days"] if d["date"] == tomorrow.isoformat())
    tomorrow_task_ids = [t.get("task_id") for t in tomorrow_day["schedule"] if t.get("type") == "task"]
    assert task_a_id in tomorrow_task_ids

    # Delete Task A (simulating calendar trash drop confirmed)
    del_res = client.delete(f"/tasks/{task_a_id}")
    assert del_res.status_code == 200
    assert f"Task {task_a_id} deleted successfully" in del_res.json()["message"]

    # Verify Task A is removed from tasks and manual placements in memory
    all_tasks = client.get("/tasks").json()
    remaining_task_ids = [t["id"] for t in all_tasks]
    assert task_a_id not in remaining_task_ids
    assert task_b_id in remaining_task_ids
    assert task_a_id not in state_module.manual_placements

    # Verify schedule no longer contains Task A
    sched_after = client.get("/schedule").json()
    all_scheduled_ids = [
        t.get("task_id")
        for day in sched_after["days"]
        for t in day["schedule"]
        if t.get("type") == "task"
    ]
    assert task_a_id not in all_scheduled_ids

    # Verify availability windows are completely intact
    avail_res = client.get("/availability").json()
    assert len(avail_res) == 2

    # Verify feedback history remains intact
    fb_res = client.get("/feedback").json()
    assert len(fb_res) == 1
    assert fb_res[0]["task_name"] == "Historical Task"

    # Simulate backend restart by re-initializing state from SQLite
    db_path = state_module.active_db_path
    assert db_path is not None
    state_module.init_state(db_path)

    # Confirm Task A did NOT return after restart
    reloaded_tasks = client.get("/tasks").json()
    reloaded_ids = [t["id"] for t in reloaded_tasks]
    assert task_a_id not in reloaded_ids
    assert task_b_id in reloaded_ids
    assert task_a_id not in state_module.manual_placements
    assert len(client.get("/availability").json()) == 2
    assert len(client.get("/feedback").json()) == 1


def test_delete_nonexistent_task_returns_404():
    response = client.delete("/tasks/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_delete_manually_placed_task_frees_slot():
    today = date.today()
    client.delete("/tasks")
    client.delete("/availability")

    client.post("/availability", json={
        "date": today.isoformat(),
        "start_time": "09:00",
        "end_time": "10:00",
    })

    # Task 1 takes the only 60m slot
    t1 = client.post("/tasks", json={
        "name": "First Task",
        "difficulty": 3,
        "duration": 60,
        "importance": 4,
    }).json()["task"]["id"]

    # Task 2 is unplaced due to lack of availability
    t2 = client.post("/tasks", json={
        "name": "Second Task",
        "difficulty": 3,
        "duration": 60,
        "importance": 3,
    }).json()["task"]["id"]

    client.post(f"/tasks/{t1}/reschedule", json={
        "date": today.isoformat(),
        "start_time": "09:00",
    })

    sched = client.get("/schedule").json()
    t1_scheduled = any(t.get("task_id") == t1 for t in sched["schedule"] if t.get("type") == "task")
    t2_scheduled = any(t.get("task_id") == t2 for t in sched["schedule"] if t.get("type") == "task")
    assert t1_scheduled is True
    assert t2_scheduled is False

    # Delete t1
    del_res = client.delete(f"/tasks/{t1}")
    assert del_res.status_code == 200

    # Now t2 should be able to schedule in the freed slot
    sched_after = client.get("/schedule").json()
    t2_scheduled_after = any(t.get("task_id") == t2 for t in sched_after["schedule"] if t.get("type") == "task")
    assert t2_scheduled_after is True


def test_productivity_insights_empty_feedback():
    client.delete("/feedback")

    res = client.get("/productivity-insights")
    assert res.status_code == 200
    data = res.json()

    assert data["total_outcomes"] == 0
    assert data["completed_count"] == 0
    assert data["completion_rate"] is None
    assert data["on_time_recorded_count"] == 0
    assert data["on_time_count"] == 0
    assert data["on_time_rate"] is None
    assert data["average_rating"] is None
    assert data["duration_metrics"]["sample_size"] == 0
    assert data["duration_metrics"]["avg_planned_duration"] is None
    assert data["duration_metrics"]["avg_actual_duration"] is None
    assert data["duration_metrics"]["duration_diff_minutes"] is None
    assert data["data_status"] == "no_data"
    assert data["sample_size_adequate"] is False
    assert "No task outcomes recorded yet" in data["summary"]
    assert "correlation does not establish causation" in data["cautionary_note"].lower()

    # Also verify alias endpoint /feedback/insights
    alias_res = client.get("/feedback/insights")
    assert alias_res.status_code == 200
    assert alias_res.json()["total_outcomes"] == 0


def test_productivity_insights_small_sample_and_metrics():
    client.delete("/feedback")

    # Item 1: completed, on_time=True, rating=5, planned=60, actual=75, energy=4, diff=4 (matched)
    r1 = client.post("/feedback", json={
        "task_name": "Task 1",
        "energy": 4,
        "difficulty": 4,
        "duration": 60,
        "actual_duration": 75,
        "completed": True,
        "on_time": True,
        "rating": 5,
        "importance": 5,
    })
    assert r1.status_code == 200

    # Item 2: not completed, on_time=None, rating=2, planned=45, actual=None (not supplied!), energy=1, diff=5 (mismatched)
    r2 = client.post("/feedback", json={
        "task_name": "Task 2",
        "energy": 1,
        "difficulty": 5,
        "duration": 45,
        "completed": False,
        "rating": 2,
        "importance": 3,
    })
    assert r2.status_code == 200

    # Item 3: completed, on_time=False, rating=None, planned=30, actual=30, energy=3, diff=2 (matched)
    r3 = client.post("/feedback", json={
        "task_name": "Task 3",
        "energy": 3,
        "difficulty": 2,
        "duration": 30,
        "actual_duration": 30,
        "completed": True,
        "completion_status": "completed",
        "on_time": False,
    })
    assert r3.status_code == 200

    res = client.get("/productivity-insights")
    assert res.status_code == 200
    data = res.json()

    assert data["total_outcomes"] == 3
    assert data["completed_count"] == 2
    assert data["completion_rate"] == 66.7

    assert data["on_time_recorded_count"] == 2
    assert data["on_time_count"] == 1
    assert data["on_time_rate"] == 50.0

    assert data["rating_recorded_count"] == 2
    assert data["average_rating"] == 3.5  # (5 + 2) / 2

    # Verify duration metrics ONLY use records where actual_duration was genuinely supplied (Task 1 and Task 3)
    dur = data["duration_metrics"]
    assert dur["sample_size"] == 2
    assert dur["avg_planned_duration"] == 45.0  # (60 + 30) / 2
    assert dur["avg_actual_duration"] == 52.5    # (75 + 30) / 2
    assert dur["duration_diff_minutes"] == 7.5   # 52.5 - 45.0

    # Small sample warning
    assert data["sample_size_adequate"] is False
    assert data["data_status"] == "insufficient_sample"
    assert "Preliminary data" in data["summary"]
    assert "minimum sample size of 5" in data["summary"]


def test_productivity_insights_adequate_sample_and_compatibility():
    client.delete("/feedback")

    # 3 matched tasks (|diff - energy| <= 1), all completed
    for i in range(3):
        r = client.post("/feedback", json={
            "task_name": f"Matched Task {i}",
            "energy": 4,
            "difficulty": 4,
            "duration": 50,
            "actual_duration": 45,
            "completed": True,
            "completion_status": "completed",
            "on_time": True,
            "rating": 5,
        })
        assert r.status_code == 200

    # 2 mismatched tasks (|diff - energy| > 1), neither completed
    for i in range(2):
        r = client.post("/feedback", json={
            "task_name": f"Mismatched Task {i}",
            "energy": 1,
            "difficulty": 4,
            "duration": 60,
            "completed": False,
            "completion_status": "skipped",
            "on_time": False,
            "rating": 2,
        })
        assert r.status_code == 200

    res = client.get("/productivity-insights")
    assert res.status_code == 200
    data = res.json()

    assert data["total_outcomes"] == 5
    assert data["completed_count"] == 3
    assert data["completion_rate"] == 60.0
    assert data["sample_size_adequate"] is True
    assert data["data_status"] == "sufficient_sample"

    compat = data["compatibility_comparison"]
    assert compat["matched"]["sample_size"] == 3
    assert compat["matched"]["completed_count"] == 3
    assert compat["matched"]["completion_rate"] == 100.0

    assert compat["mismatched"]["sample_size"] == 2
    assert compat["mismatched"]["completed_count"] == 0
    assert compat["mismatched"]["completion_rate"] == 0.0

    # Summary explicitly reports N counts and rates
    assert "100.0% completion rate (N=3)" in data["summary"]
    assert "0.0% for mismatched tasks (N=2)" in data["summary"]
    assert data["cautionary_note"] is not None


def test_feedback_actual_duration_and_importance_persistence():
    client.delete("/feedback")

    post_res = client.post("/feedback", json={
        "task_name": "Deep Dive Refactoring",
        "task_id": 101,
        "energy": 4,
        "difficulty": 4,
        "duration": 90,
        "actual_duration": 80,
        "importance": 5,
        "completed": True,
        "on_time": True,
        "rating": 5,
        "completion_status": "completed",
    })
    assert post_res.status_code == 200

    # Verify endpoint GET /feedback
    fb_list = client.get("/feedback").json()
    assert len(fb_list) == 1
    assert fb_list[0]["actual_duration"] == 80
    assert fb_list[0]["importance"] == 5

    # Reinitialize backend state from SQLite
    db_path = state_module.active_db_path
    assert db_path is not None
    state_module.init_state(db_path)

    # Verify both fields survived reload in state and API
    reloaded_fb = client.get("/feedback").json()
    assert len(reloaded_fb) == 1
    assert reloaded_fb[0]["actual_duration"] == 80
    assert reloaded_fb[0]["importance"] == 5
    assert reloaded_fb[0]["task_name"] == "Deep Dive Refactoring"

    # Verify insights calculate properly after reload
    insights = client.get("/productivity-insights").json()
    assert insights["duration_metrics"]["sample_size"] == 1
    assert insights["duration_metrics"]["avg_actual_duration"] == 80.0
    assert insights["duration_metrics"]["avg_planned_duration"] == 90.0
    assert insights["duration_metrics"]["duration_diff_minutes"] == -10.0



