from fastapi import APIRouter, HTTPException

from models.schemas import Availability, TimeBlock
from services import db
from services import state as state_module

router = APIRouter()


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
