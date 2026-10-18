from fastapi import APIRouter, HTTPException

from models.schemas import Availability, TimeBlock
from services import state as state_module

router = APIRouter()


@router.post("/time-blocks")
def add_time_block(block: TimeBlock):
    if block.start_time >= block.end_time:
        return {"message": "End time must be after start time"}
    state_module.time_blocks.append(block)
    return {"message": "Time block added successfully", "block": block}


@router.get("/time-blocks")
def get_time_blocks():
    return state_module.time_blocks


@router.delete("/time-blocks")
def clear_time_blocks():
    state_module.time_blocks.clear()
    return {"message": "All time blocks cleared"}


@router.post("/availability")
def add_availability(window: Availability):
    if window.start_time >= window.end_time:
        return {"message": "End time must be after start time"}
    added = state_module.add_availability_window(window)
    if not added:
        return {"message": "Availability window already exists", "window": window}
    return {"message": "Availability window added successfully", "window": window}


@router.get("/availability")
def get_availability():
    return state_module.availability_windows


@router.delete("/availability")
def clear_availability():
    state_module.availability_windows.clear()
    return {"message": "All availability windows cleared"}


@router.delete("/availability/window")
def delete_availability_window(date: str, start_time: str, end_time: str):
    initial_len = len(state_module.availability_windows)
    state_module.availability_windows = [
        window
        for window in state_module.availability_windows
        if not (
            str(window.date) == date
            and window.start_time == start_time
            and window.end_time == end_time
        )
    ]
    if len(state_module.availability_windows) < initial_len:
        return {"message": "Availability window removed"}
    raise HTTPException(status_code=404, detail="Availability window not found")
