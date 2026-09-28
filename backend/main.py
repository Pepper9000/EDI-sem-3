from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sklearn.linear_model import LogisticRegression

app = FastAPI(title="Chronos", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Task(BaseModel):
    id: int | None = None
    name: str = Field(..., min_length=1)
    difficulty: int = Field(ge=1, le=5)
    duration: int = Field(gt=0)
    importance: int = Field(ge=1, le=5)
    deadline: date | None = None


class Energy(BaseModel):
    level: int = Field(ge=1, le=5)


class Feedback(BaseModel):
    task_name: str
    energy: int = Field(ge=1, le=5)
    difficulty: int = Field(ge=1, le=5)
    duration: int = Field(gt=0)
    completed: bool
    on_time: bool
    rating: int = Field(ge=1, le=5)


class TimeBlock(BaseModel):
    date: date
    start_time: str
    end_time: str
    type: str = "busy"


class Availability(BaseModel):
    date: date
    start_time: str
    end_time: str


class WearableData(BaseModel):
    sleep_hours: float = Field(ge=0, le=24)
    resting_heart_rate: int = Field(gt=0)
    hrv: float = Field(ge=0)
    steps: int = Field(ge=0)
    active_minutes: int = Field(ge=0)


tasks: list[Task] = []
current_energy = 3
feedback_data: list[Feedback] = []
time_blocks: list[TimeBlock] = []
availability_windows: list[Availability] = []
wearable_data: WearableData | None = None
next_task_id = 1


def assign_task_id(task: Task) -> None:
    global next_task_id
    if task.id is None:
        task.id = next_task_id
        next_task_id += 1


def time_to_minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def minutes_to_time(minutes: int) -> str:
    hour = minutes // 60
    minute = minutes % 60
    return f"{hour:02d}:{minute:02d}"


def circadian_energy() -> int:
    hour = datetime.now().hour
    if 9 <= hour < 12:
        return 5
    if 12 <= hour < 14:
        return 3
    if 14 <= hour < 17:
        return 4
    if 17 <= hour < 20:
        return 3
    if 20 <= hour < 22:
        return 2
    return 1


def wearable_energy() -> int:
    if wearable_data is None:
        return current_energy

    score = 0
    if wearable_data.sleep_hours >= 8:
        score += 2
    elif wearable_data.sleep_hours >= 6:
        score += 1
    if wearable_data.resting_heart_rate < 65:
        score += 1
    if wearable_data.hrv >= 50:
        score += 1
    if wearable_data.steps >= 7000:
        score += 1
    return max(1, min(5, score))


def get_effective_energy() -> int:
    time_energy = circadian_energy()
    watch_energy = wearable_energy()
    return max(1, min(5, round((current_energy + time_energy + watch_energy) / 3)))


def urgency_score(task: Task) -> int:
    if task.deadline is None:
        return 0
    remaining_days = (task.deadline - date.today()).days
    if remaining_days <= 0:
        return 5
    if remaining_days == 1:
        return 4
    if remaining_days <= 3:
        return 3
    if remaining_days <= 7:
        return 2
    return 1


def energy_fit_score(task: Task, energy_level: int) -> int:
    return max(1, min(5, 6 - abs(task.difficulty - energy_level)))


def train_model():
    if len(feedback_data) < 4:
        return None

    X = []
    y = []
    for feedback in feedback_data:
        X.append([feedback.energy, feedback.difficulty, feedback.duration])
        y.append(1 if feedback.completed else 0)

    if len(set(y)) < 2:
        return None

    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)
    return model


@app.get("/")
def home():
    frontend_path = Path(__file__).parent / "frontend" / "index.html"
    return FileResponse(frontend_path)


@app.post("/tasks")
def add_task(task: Task):
    assign_task_id(task)
    tasks.append(task)
    return {"message": "Task added successfully", "task": task}


@app.get("/tasks")
def get_tasks():
    return tasks


@app.delete("/tasks")
def clear_tasks():
    tasks.clear()
    return {"message": "All tasks cleared"}


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    for index, task in enumerate(tasks):
        if task.id == task_id:
            del tasks[index]
            return {"message": f"Task {task_id} deleted successfully"}
    raise HTTPException(status_code=404, detail="Task not found")


@app.post("/energy")
def set_energy(energy: Energy):
    global current_energy
    current_energy = energy.level
    return {"message": "Energy level updated", "energy": current_energy}


@app.get("/energy")
def get_energy():
    return {"energy": current_energy}


@app.post("/wearable-data")
def add_wearable_data(data: WearableData):
    global wearable_data
    wearable_data = data
    return {"message": "Wearable data received successfully", "data": wearable_data}


@app.get("/wearable-data")
def get_wearable_data():
    if wearable_data is None:
        return {"message": "No wearable data available"}
    return wearable_data


@app.get("/biological-state")
def biological_state():
    return {
        "manual_energy": current_energy,
        "circadian_energy": circadian_energy(),
        "wearable_energy": wearable_energy(),
        "effective_energy": get_effective_energy(),
    }


def conflicts_with_busy(start: int, end: int, schedule_date: date) -> bool:
    for block in time_blocks:
        if block.type != "busy" or block.date != schedule_date:
            continue
        block_start = time_to_minutes(block.start_time)
        block_end = time_to_minutes(block.end_time)
        if start < block_end and end > block_start:
            return True
    return False


def find_task_slot(task_duration: int, schedule_date: date) -> int | None:
    for window in availability_windows:
        if window.date != schedule_date:
            continue

        window_start = time_to_minutes(window.start_time)
        window_end = time_to_minutes(window.end_time)
        start_candidate = window_start

        while start_candidate + task_duration <= window_end:
            if not conflicts_with_busy(start_candidate, start_candidate + task_duration, schedule_date):
                return start_candidate
            start_candidate += 15

    return None


def build_reason_list(task: Task, energy_level: int, urgency: int, probability: float) -> list[str]:
    reasons: list[str] = []
    if task.difficulty >= 4:
        reasons.append("High difficulty")
    if task.importance >= 4:
        reasons.append("High importance")
    if urgency >= 3:
        reasons.append("Deadline approaching")
    if abs(task.difficulty - energy_level) <= 1:
        reasons.append("Good energy match")
    elif task.difficulty > energy_level:
        reasons.append("Better suited to a higher-energy period")
    else:
        reasons.append("Lower complexity fits current energy")
    if probability >= 0.7:
        reasons.append("Strong completion likelihood")
    elif probability < 0.4:
        reasons.append("Model confidence is still modest")
    return reasons[:4]


@app.get("/schedule")
def generate_schedule():
    schedule_date = date.today()
    effective_energy = get_effective_energy()

    if not availability_windows:
        return {
            "date": str(schedule_date),
            "energy": current_energy,
            "effective_energy": effective_energy,
            "schedule": [],
            "message": "No availability windows have been configured yet. Add one or more free windows before generating a schedule.",
        }

    model = train_model()
    scored_tasks = []

    for task in tasks:
        if model is not None:
            probability = model.predict_proba([[effective_energy, task.difficulty, task.duration]])[0][1]
        else:
            probability = 0.5

        urgency = urgency_score(task)
        energy_fit = energy_fit_score(task, effective_energy)
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

    scheduled_entries = []
    for item in scored_tasks:
        task = item["task"]
        slot = find_task_slot(task.duration, schedule_date)
        if slot is None:
            scheduled_entries.append({
                "task": task.name,
                "difficulty": task.difficulty,
                "importance": task.importance,
                "duration": task.duration,
                "type": "unscheduled",
                "reason": "No suitable time slot in your configured availability windows.",
            })
            continue

        start_time = minutes_to_time(slot)
        end_time = minutes_to_time(slot + task.duration)
        reason = build_reason_list(task, effective_energy, item["urgency"], item["probability"])

        scheduled_entries.append({
            "task": task.name,
            "difficulty": task.difficulty,
            "importance": task.importance,
            "duration": task.duration,
            "start_time": start_time,
            "end_time": end_time,
            "type": "task",
            "energy_fit": item["energy_fit"],
            "urgency": item["urgency"],
            "predicted_success": round(item["probability"], 2),
            "reason": reason,
            "start_minute": slot,
            "end_minute": slot + task.duration,
        })

    scheduled_entries.sort(key=lambda item: item.get("start_minute", 9999))
    final_schedule = []
    for index, item in enumerate(scheduled_entries):
        if item.get("type") == "task":
            if index > 0 and final_schedule and final_schedule[-1]["type"] == "task":
                gap = item["start_minute"] - final_schedule[-1]["end_minute"]
                if gap >= 30:
                    break_start = final_schedule[-1]["end_minute"]
                    break_end = item["start_minute"]
                    final_schedule.append({
                        "task": "Break",
                        "duration": break_end - break_start,
                        "start_time": minutes_to_time(break_start),
                        "end_time": minutes_to_time(break_end),
                        "type": "break",
                        "reason": ["Recovery break between work blocks"],
                    })
            final_schedule.append(item)
        else:
            final_schedule.append(item)

    return {
        "date": str(schedule_date),
        "energy": current_energy,
        "circadian_energy": circadian_energy(),
        "wearable_energy": wearable_energy(),
        "effective_energy": effective_energy,
        "schedule": final_schedule,
        "message": "Schedule generated from energy fit, task priority, and availability.",
    }


@app.post("/feedback")
def add_feedback(feedback: Feedback):
    feedback_data.append(feedback)
    return {"message": "Feedback recorded successfully", "feedback": feedback}


@app.get("/feedback")
def get_feedback():
    return feedback_data


@app.delete("/feedback")
def clear_feedback():
    feedback_data.clear()
    return {"message": "All feedback cleared"}


@app.get("/ml-status")
def get_ml_status():
    model = train_model()
    feedback_count = len(feedback_data)
    if model is not None:
        return {
            "status": "ready",
            "feedback_records": feedback_count,
            "model_status": "Ready",
            "learning_signal": "Task completion prediction",
            "message": "The current model can use feedback to predict whether a task is likely to be completed.",
        }

    return {
        "status": "collecting_feedback",
        "feedback_records": feedback_count,
        "model_status": "Collecting feedback",
        "learning_signal": "Task completion prediction",
        "message": "Collecting feedback. The model needs more varied feedback before training.",
    }


@app.post("/time-blocks")
def add_time_block(block: TimeBlock):
    if block.start_time >= block.end_time:
        return {"message": "End time must be after start time"}
    time_blocks.append(block)
    return {"message": "Time block added successfully", "block": block}


@app.get("/time-blocks")
def get_time_blocks():
    return time_blocks


@app.delete("/time-blocks")
def clear_time_blocks():
    time_blocks.clear()
    return {"message": "All time blocks cleared"}


@app.post("/availability")
def add_availability(window: Availability):
    if window.start_time >= window.end_time:
        return {"message": "End time must be after start time"}
    availability_windows.append(window)
    return {"message": "Availability window added successfully", "window": window}


@app.get("/availability")
def get_availability():
    return availability_windows


@app.delete("/availability")
def clear_availability():
    availability_windows.clear()
    return {"message": "All availability windows cleared"}