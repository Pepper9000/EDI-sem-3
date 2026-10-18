from fastapi import APIRouter, HTTPException

from models.schemas import RescheduleTaskRequest, Task
from services import state as state_module
from services.scheduler import validate_task_reschedule

router = APIRouter()


@router.post("/tasks")
def add_task(task: Task):
    state_module.assign_task_id(task)
    state_module.tasks.append(task)
    return {"message": "Task added successfully", "task": task}


@router.get("/tasks")
def get_tasks():
    return state_module.tasks


@router.delete("/tasks")
def clear_tasks():
    state_module.tasks.clear()
    state_module.manual_placements.clear()
    return {"message": "All tasks cleared"}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    for index, task in enumerate(state_module.tasks):
        if task.id == task_id:
            del state_module.tasks[index]
            state_module.manual_placements.pop(task_id, None)
            return {"message": f"Task {task_id} deleted successfully"}
    raise HTTPException(status_code=404, detail="Task not found")


@router.post("/tasks/{task_id}/reschedule")
def reschedule_task(task_id: int, request: RescheduleTaskRequest):
    is_valid, error_msg, start_min, end_min = validate_task_reschedule(
        task_id, request.date, request.start_time
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    state_module.manual_placements[task_id] = {
        "date": request.date,
        "start_time": request.start_time,
    }
    return {
        "message": f"Task {task_id} successfully rescheduled to {request.date} at {request.start_time}",
        "task_id": task_id,
        "date": str(request.date),
        "start_time": request.start_time,
        "end_time": state_module.minutes_to_time(end_min),
    }


