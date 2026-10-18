from datetime import date, timedelta

from ml.personalization import train_model
from services import state as state_module


def validate_task_reschedule(
    task_id: int, target_date: date, start_time: str
) -> tuple[bool, str | None, int, int]:
    task = next((t for t in state_module.tasks if t.id == task_id), None)
    if task is None:
        return False, "Task not found.", 0, 0

    planning_start = date.today()
    horizon_dates = [planning_start + timedelta(days=i) for i in range(7)]

    if target_date < planning_start or target_date > horizon_dates[-1]:
        return (
            False,
            f"Proposed date {target_date} is outside the strict seven-day planning horizon ({planning_start} to {horizon_dates[-1]}).",
            0,
            0,
        )

    try:
        start_min = state_module.time_to_minutes(start_time)
    except Exception:
        return False, "Invalid start time format. Use HH:MM.", 0, 0

    if start_min % 15 != 0:
        return False, "Proposed start time must be aligned to 15-minute increments.", 0, 0

    if task.deadline is not None and target_date > task.deadline:
        return (
            False,
            f"Cannot schedule task after its deadline ({task.deadline}).",
            0,
            0,
        )

    end_min = start_min + task.duration
    cutoff = state_module.time_to_minutes(state_module.end_of_day)
    if end_min > cutoff:
        return (
            False,
            f"Task ends at {state_module.minutes_to_time(end_min)}, which exceeds the {state_module.end_of_day} cutoff.",
            0,
            0,
        )

    if not state_module.interval_is_available(start_min, end_min, target_date):
        return (
            False,
            "Proposed time slot is outside your configured availability windows or conflicts with a busy block.",
            0,
            0,
        )

    # Check overlaps against other tasks on target_date
    saved_placement = state_module.manual_placements.pop(task_id, None)
    try:
        schedule_payload = generate_schedule_payload()
        target_day = next(
            (day for day in schedule_payload["days"] if day["date"] == str(target_date)),
            None,
        )
        if target_day:
            for item in target_day["schedule"]:
                if item.get("type") == "task" and item.get("task_id") != task_id:
                    o_start = item["start_minute"]
                    o_end = item["end_minute"]
                    if start_min < o_end and end_min > o_start:
                        return (
                            False,
                            f"Proposed slot ({start_time} - {state_module.minutes_to_time(end_min)}) overlaps with task '{item['task']}' ({item['start_time']} - {item['end_time']}).",
                            0,
                            0,
                        )
    finally:
        if saved_placement is not None:
            state_module.manual_placements[task_id] = saved_placement

    return True, None, start_min, end_min


def generate_schedule_payload(target_date_str: str | None = None) -> dict:
    planning_start = date.today()
    horizon_dates = [planning_start + timedelta(days=i) for i in range(7)]
    effective_energy = state_module.get_effective_energy()
    cutoff = state_module.time_to_minutes(state_module.end_of_day)

    target_date = planning_start
    if target_date_str:
        try:
            parsed = date.fromisoformat(target_date_str)
            if parsed in horizon_dates:
                target_date = parsed
        except ValueError:
            target_date = planning_start

    # If no availability windows exist at all in the system
    if not state_module.availability_windows:
        unscheduled_tasks = [{
            "task_id": task.id,
            "task": task.name,
            "difficulty": task.difficulty,
            "importance": task.importance,
            "duration": task.duration,
            "type": "unscheduled",
            "reason": "No availability windows have been configured yet.",
        } for task in state_module.tasks]

        days = []
        for d in horizon_dates:
            day_schedule = unscheduled_tasks if d == target_date else []
            days.append({
                "date": str(d),
                "day_name": d.strftime("%A"),
                "short_date": d.strftime("%b %d"),
                "is_today": d == planning_start,
                "available_minutes": 0,
                "scheduled_minutes": 0,
                "unused_minutes": 0,
                "unscheduled_count": len(unscheduled_tasks) if d == target_date else 0,
                "schedule": day_schedule,
            })

        weekly_overview = [{
            "date": str(d),
            "day_name": d.strftime("%A"),
            "short_date": d.strftime("%b %d"),
            "is_today": d == planning_start,
            "available_minutes": 0,
            "scheduled_minutes": 0,
            "unused_minutes": 0,
            "tasks": [],
        } for d in horizon_dates]

        target_day = next(day for day in days if day["date"] == str(target_date))

        return {
            "date": str(target_date),
            "energy": state_module.current_energy,
            "circadian_energy": state_module.circadian_energy(),
            "wearable_energy": state_module.wearable_energy(),
            "effective_energy": effective_energy,
            "end_of_day": state_module.end_of_day,
            "available_minutes": 0,
            "scheduled_minutes": 0,
            "unused_minutes": 0,
            "unscheduled_count": len(unscheduled_tasks),
            "tasks_total": len(state_module.tasks),
            "schedule": target_day["schedule"],
            "days": days,
            "weekly_overview": weekly_overview,
            "unscheduled_tasks": unscheduled_tasks,
            "horizon_start": str(horizon_dates[0]),
            "horizon_end": str(horizon_dates[-1]),
            "message": "No availability windows have been configured yet. Add one or more free windows before generating a schedule.",
        }

    model = train_model()
    scored_tasks = []

    for task in state_module.tasks:
        if model is not None:
            probability = model.predict_proba([[effective_energy, task.difficulty, task.duration]])[0][1]
        else:
            probability = 0.5

        urgency = state_module.urgency_score(task, planning_start)
        energy_fit = state_module.energy_fit_score(task, effective_energy)
        score = (
            probability * 0.30
            + energy_fit * 0.30
            + task.importance * 1.2
            + urgency * 0.75
            + task.difficulty * 0.45
        )
        scored_tasks.append({
            "task": task,
            "score": score,
            "probability": probability,
            "energy_fit": energy_fit,
            "urgency": urgency,
        })

    scored_tasks.sort(key=lambda item: item["score"], reverse=True)

    day_reserved: dict[date, list[tuple[int, int]]] = {d: [] for d in horizon_dates}
    day_scheduled_tasks: dict[date, list[dict]] = {d: [] for d in horizon_dates}
    unscheduled_tasks: list[dict] = []
    unscheduled_by_date: dict[date, list[dict]] = {d: [] for d in horizon_dates}
    manually_placed_ids: set[int] = set()

    # Lock in manual placements that remain valid without conflicts
    for task_id, placement in list(state_module.manual_placements.items()):
        task = next((t for t in state_module.tasks if t.id == task_id), None)
        if task is None:
            continue
        p_date = placement.get("date")
        p_start_str = placement.get("start_time")
        if not p_date or not p_start_str or p_date not in horizon_dates:
            continue
        if task.deadline is not None and p_date > task.deadline:
            continue
        try:
            p_start = state_module.time_to_minutes(p_start_str)
        except Exception:
            continue
        p_end = p_start + task.duration
        if p_end > cutoff:
            continue
        if not state_module.interval_is_available(p_start, p_end, p_date):
            continue
        if state_module.conflicts_with_reserved(p_start, p_end, day_reserved[p_date]):
            continue

        day_reserved[p_date].append((p_start, p_end))
        task_urgency = state_module.urgency_score(task, planning_start)
        reason = state_module.build_reason_list(task, effective_energy, task_urgency, 0.5)

        day_scheduled_tasks[p_date].append({
            "task_id": task.id,
            "task": task.name,
            "difficulty": task.difficulty,
            "importance": task.importance,
            "duration": task.duration,
            "start_time": p_start_str,
            "end_time": state_module.minutes_to_time(p_end),
            "date": str(p_date),
            "type": "task",
            "energy_fit": state_module.energy_fit_score(task, effective_energy),
            "urgency": task_urgency,
            "predicted_success": 0.5,
            "reason": reason,
            "start_minute": p_start,
            "end_minute": p_end,
            "is_manual": True,
        })
        manually_placed_ids.add(task.id)

    # Schedule remaining unplaced tasks
    for item in scored_tasks:
        task = item["task"]
        if task.id in manually_placed_ids:
            continue

        placed = False

        for candidate_date in horizon_dates:
            # Enforce deadline constraint: never schedule past task deadline
            if task.deadline is not None and candidate_date > task.deadline:
                break

            slot = state_module.find_task_slot(task.duration, candidate_date, day_reserved[candidate_date])
            if slot is not None:
                day_reserved[candidate_date].append((slot, slot + task.duration))
                start_time = state_module.minutes_to_time(slot)
                end_time = state_module.minutes_to_time(slot + task.duration)
                reason = state_module.build_reason_list(task, effective_energy, item["urgency"], item["probability"])

                day_scheduled_tasks[candidate_date].append({
                    "task_id": task.id,
                    "task": task.name,
                    "difficulty": task.difficulty,
                    "importance": task.importance,
                    "duration": task.duration,
                    "start_time": start_time,
                    "end_time": end_time,
                    "date": str(candidate_date),
                    "type": "task",
                    "energy_fit": item["energy_fit"],
                    "urgency": item["urgency"],
                    "predicted_success": round(item["probability"], 2),
                    "reason": reason,
                    "start_minute": slot,
                    "end_minute": slot + task.duration,
                })
                placed = True
                break

        if not placed:
            if task.deadline is not None and task.deadline < planning_start:
                reason = f"Deadline {task.deadline} has already passed."
                target_day_for_unplaced = planning_start
            elif task.deadline is not None and task.deadline == planning_start:
                reason = "Does not fit in today's availability and deadline prevents scheduling on future dates."
                target_day_for_unplaced = planning_start
            elif task.deadline is not None and task.deadline in horizon_dates:
                reason = f"No suitable time slot before deadline {task.deadline} within the seven-day planning horizon."
                target_day_for_unplaced = task.deadline
            else:
                reason = "No suitable time slot available within the strict seven-day planning horizon."
                target_day_for_unplaced = planning_start

            unplaced_entry = {
                "task_id": task.id,
                "task": task.name,
                "difficulty": task.difficulty,
                "importance": task.importance,
                "duration": task.duration,
                "type": "unscheduled",
                "reason": reason,
            }
            unscheduled_tasks.append(unplaced_entry)
            unscheduled_by_date[target_day_for_unplaced].append(unplaced_entry)

    # Build schedules with recovery breaks for each day
    days = []
    weekly_overview = []

    for d in horizon_dates:
        tasks_on_day = sorted(day_scheduled_tasks[d], key=lambda item: item.get("start_minute", 9999))
        final_day_schedule = []

        for index, item in enumerate(tasks_on_day):
            if index > 0 and final_day_schedule and final_day_schedule[-1]["type"] == "task":
                gap = item["start_minute"] - final_day_schedule[-1]["end_minute"]
                if gap >= 30:
                    break_start = final_day_schedule[-1]["end_minute"]
                    break_end = break_start + 15
                    if state_module.interval_is_available(break_start, break_end, d):
                        final_day_schedule.append({
                            "task": "Break",
                            "duration": 15,
                            "start_time": state_module.minutes_to_time(break_start),
                            "end_time": state_module.minutes_to_time(break_end),
                            "date": str(d),
                            "type": "break",
                            "reason": ["15-minute recovery break between work blocks"],
                        })
            final_day_schedule.append(item)

        # Include unplaced tasks assigned to this date
        final_day_schedule.extend(unscheduled_by_date[d])

        available_cap = state_module.available_minutes(d)
        scheduled_mins = sum(
            entry["duration"] for entry in final_day_schedule if entry.get("type") == "task"
        )
        unused_mins = max(0, available_cap - scheduled_mins)
        unscheduled_cnt = sum(
            1 for entry in final_day_schedule if entry.get("type") == "unscheduled"
        )

        days.append({
            "date": str(d),
            "day_name": d.strftime("%A"),
            "short_date": d.strftime("%b %d"),
            "is_today": d == planning_start,
            "available_minutes": available_cap,
            "scheduled_minutes": scheduled_mins,
            "unused_minutes": unused_mins,
            "unscheduled_count": unscheduled_cnt,
            "schedule": final_day_schedule,
        })

        weekly_overview.append({
            "date": str(d),
            "day_name": d.strftime("%A"),
            "short_date": d.strftime("%b %d"),
            "is_today": d == planning_start,
            "available_minutes": available_cap,
            "scheduled_minutes": scheduled_mins,
            "unused_minutes": unused_mins,
            "tasks": [
                {
                    "task_id": t["task_id"],
                    "name": t["task"],
                    "duration": t["duration"],
                    "start_time": t["start_time"],
                    "end_time": t["end_time"],
                }
                for t in final_day_schedule
                if t.get("type") == "task"
            ],
        })

    target_day = next((day for day in days if day["date"] == str(target_date)), days[0])

    return {
        "date": str(target_date),
        "energy": state_module.current_energy,
        "circadian_energy": state_module.circadian_energy(),
        "wearable_energy": state_module.wearable_energy(),
        "effective_energy": effective_energy,
        "end_of_day": state_module.end_of_day,
        "available_minutes": target_day["available_minutes"],
        "scheduled_minutes": target_day["scheduled_minutes"],
        "unused_minutes": target_day["unused_minutes"],
        "unscheduled_count": target_day["unscheduled_count"],
        "tasks_total": len(state_module.tasks),
        "schedule": target_day["schedule"],
        "days": days,
        "weekly_overview": weekly_overview,
        "unscheduled_tasks": unscheduled_tasks,
        "horizon_start": str(horizon_dates[0]),
        "horizon_end": str(horizon_dates[-1]),
        "message": "Seven-day schedule generated from energy fit, task priority, and availability.",
    }
