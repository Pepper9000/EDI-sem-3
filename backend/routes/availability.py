from datetime import date, timedelta
from fastapi import APIRouter, HTTPException

from models.schemas import Availability, TimeBlock, WeeklyAvailabilityRequest
from services import db
from services import state as state_module

router = APIRouter()

WEEKDAY_NAME_TO_INT = {
    "monday": 0, "mon": 0, "0": 0,
    "tuesday": 1, "tue": 1, "1": 1,
    "wednesday": 2, "wed": 2, "2": 2,
    "thursday": 3, "thu": 3, "3": 3,
    "friday": 4, "fri": 4, "4": 4,
    "saturday": 5, "sat": 5, "5": 5,
    "sunday": 6, "sun": 6, "6": 6,
}


def parse_weekdays(weekdays_input: list[str | int]) -> set[int]:
    result: set[int] = set()
    for item in weekdays_input:
        if isinstance(item, int):
            if 0 <= item <= 6:
                result.add(item)
        else:
            val = str(item).strip().lower()
            if val in WEEKDAY_NAME_TO_INT:
                result.add(WEEKDAY_NAME_TO_INT[val])
    return result


@router.post("/time-blocks")
def add_time_block(block: TimeBlock):
    if block.start_time >= block.end_time:
        return {"message": "End time must be after start time"}
    try:
        db.add_time_block(block, db_path=state_module.active_db_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    state_module.time_blocks.append(block)
    return {"message": "Time block added successfully", "block": block}


@router.get("/time-blocks")
def get_time_blocks():
    return state_module.time_blocks


@router.delete("/time-blocks")
def clear_time_blocks():
    try:
        db.clear_time_blocks(db_path=state_module.active_db_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    state_module.time_blocks.clear()
    return {"message": "All time blocks cleared"}


@router.post("/availability")
def add_availability(window: Availability):
    if window.start_time >= window.end_time:
        return {"message": "End time must be after start time"}
    for existing in state_module.availability_windows:
        if (
            existing.date == window.date
            and existing.start_time == window.start_time
            and existing.end_time == window.end_time
        ):
            return {"message": "Availability window already exists", "window": window}
    try:
        added = db.add_availability(window, db_path=state_module.active_db_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    if not added:
        return {"message": "Availability window already exists", "window": window}
    state_module.availability_windows.append(window)
    return {"message": "Availability window added successfully", "window": window}


@router.get("/availability")
def get_availability():
    return state_module.availability_windows


@router.delete("/availability")
def clear_availability():
    try:
        db.clear_availability(db_path=state_module.active_db_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    state_module.availability_windows.clear()
    return {"message": "All availability windows cleared"}


@router.delete("/availability/window")
def delete_availability_window(date: str, start_time: str, end_time: str):
    matching = any(
        str(window.date) == date
        and window.start_time == start_time
        and window.end_time == end_time
        for window in state_module.availability_windows
    )
    if not matching:
        raise HTTPException(status_code=404, detail="Availability window not found")

    try:
        db.delete_availability_window(
            date, start_time, end_time, db_path=state_module.active_db_path
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    state_module.availability_windows = [
        window
        for window in state_module.availability_windows
        if not (
            str(window.date) == date
            and window.start_time == start_time
            and window.end_time == end_time
        )
    ]
    return {"message": "Availability window removed"}


@router.post("/availability/weekly/preview")
def preview_weekly_availability(request: WeeklyAvailabilityRequest):
    try:
        s_min = state_module.time_to_minutes(request.start_time)
        e_min = state_module.time_to_minutes(request.end_time)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM.") from exc

    if s_min >= e_min:
        raise HTTPException(status_code=400, detail="End time must be after start time.")

    target_weekdays = parse_weekdays(request.weekdays)
    if not target_weekdays:
        raise HTTPException(status_code=400, detail="At least one valid weekday must be selected.")

    planning_start = date.today()
    horizon_dates = [planning_start + timedelta(days=i) for i in range(7)]
    matching_dates = [d for d in horizon_dates if d.weekday() in target_weekdays]

    preview_items: list[dict] = []
    will_add_count = 0
    already_exists_count = 0

    for d in matching_dates:
        is_duplicate = any(
            w.date == d
            and w.start_time == request.start_time
            and w.end_time == request.end_time
            for w in state_module.availability_windows
        )
        if is_duplicate:
            already_exists_count += 1
            preview_items.append({
                "date": str(d),
                "day_name": d.strftime("%A"),
                "short_date": d.strftime("%b %d"),
                "status": "already_exists",
                "start_time": request.start_time,
                "end_time": request.end_time,
                "message": "Window already exists on this date",
            })
        else:
            will_add_count += 1
            preview_items.append({
                "date": str(d),
                "day_name": d.strftime("%A"),
                "short_date": d.strftime("%b %d"),
                "status": "will_add",
                "start_time": request.start_time,
                "end_time": request.end_time,
                "message": "Will be added",
            })

    return {
        "matching_dates": preview_items,
        "will_add_count": will_add_count,
        "already_exists_count": already_exists_count,
        "total_matching": len(preview_items),
    }


@router.post("/availability/weekly")
def add_weekly_availability(request: WeeklyAvailabilityRequest):
    try:
        s_min = state_module.time_to_minutes(request.start_time)
        e_min = state_module.time_to_minutes(request.end_time)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM.") from exc

    if s_min >= e_min:
        raise HTTPException(status_code=400, detail="End time must be after start time.")

    target_weekdays = parse_weekdays(request.weekdays)
    if not target_weekdays:
        raise HTTPException(status_code=400, detail="At least one valid weekday must be selected.")

    # Strict seven-day planning horizon: today and the next six calendar days
    planning_start = date.today()
    horizon_dates = [planning_start + timedelta(days=i) for i in range(7)]
    matching_dates = [d for d in horizon_dates if d.weekday() in target_weekdays]

    created: list[dict] = []
    skipped: list[dict] = []
    to_create_objs: list[Availability] = []

    for d in matching_dates:
        is_duplicate = any(
            w.date == d
            and w.start_time == request.start_time
            and w.end_time == request.end_time
            for w in state_module.availability_windows
        )
        if is_duplicate:
            skipped.append({
                "date": str(d),
                "day_name": d.strftime("%A"),
                "start_time": request.start_time,
                "end_time": request.end_time,
                "reason": "Window already exists on this date",
            })
        else:
            win_obj = Availability(
                date=d,
                start_time=request.start_time,
                end_time=request.end_time,
            )
            to_create_objs.append(win_obj)
            created.append({
                "date": str(d),
                "day_name": d.strftime("%A"),
                "start_time": request.start_time,
                "end_time": request.end_time,
            })

    if to_create_objs:
        try:
            db.add_availability_batch(to_create_objs, db_path=state_module.active_db_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

        # Only mutate in-memory state after successful database persistence
        state_module.availability_windows.extend(to_create_objs)

    return {
        "message": f"Created {len(created)} availability windows, skipped {len(skipped)} duplicates.",
        "created": created,
        "skipped": skipped,
        "total_created": len(created),
        "total_skipped": len(skipped),
    }
