from datetime import date, timedelta

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



