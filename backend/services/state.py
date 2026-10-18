from datetime import date, datetime
from pathlib import Path

from models.schemas import Availability, Feedback, Task, TimeBlock, WearableData
from services import db


active_db_path: Path | None = None

tasks: list[Task] = []
current_energy = 3
feedback_data: list[Feedback] = []
time_blocks: list[TimeBlock] = []
availability_windows: list[Availability] = []
wearable_data: WearableData | None = None
next_task_id = 1
end_of_day = "22:00"
manual_placements: dict[int, dict] = {}


def init_state(db_path: Path | str | None = None) -> None:
    global active_db_path, tasks, current_energy, feedback_data, time_blocks
    global availability_windows, wearable_data, next_task_id, end_of_day, manual_placements

    target_path = Path(db_path).resolve() if db_path else db.get_default_db_path()
    active_db_path = target_path
    data = db.load_all(target_path)

    tasks = data["tasks"]
    manual_placements = data["manual_placements"]
    availability_windows = data["availability"]
    time_blocks = data["time_blocks"]
    current_energy = data["settings"]["current_energy"]
    end_of_day = data["settings"]["end_of_day"]
    wearable_data = data["settings"]["wearable_data"]
    feedback_data = data["feedback"]
    next_task_id = data["next_task_id"]


def assign_task_id(task: Task) -> None:
    global next_task_id
    if task.id is None:
        task.id = next_task_id
        next_task_id += 1
    else:
        if task.id >= next_task_id:
            next_task_id = task.id + 1


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


def urgency_score(task: Task, current_date: date | None = None) -> int:
    if task.deadline is None:
        return 0
    today = current_date or date.today()
    remaining_days = (task.deadline - today).days
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


def add_availability_window(window: Availability) -> bool:
    for existing in availability_windows:
        if (
            existing.date == window.date
            and existing.start_time == window.start_time
            and existing.end_time == window.end_time
        ):
            return False
    availability_windows.append(window)
    return True


def conflicts_with_busy(start: int, end: int, schedule_date: date) -> bool:
    for block in time_blocks:
        if block.type != "busy" or block.date != schedule_date:
            continue
        block_start = time_to_minutes(block.start_time)
        block_end = time_to_minutes(block.end_time)
        if start < block_end and end > block_start:
            return True
    return False


def get_merged_availability_intervals(schedule_date: date) -> list[tuple[int, int]]:
    cutoff = time_to_minutes(end_of_day)
    intervals: list[tuple[int, int]] = []
    for window in availability_windows:
        if window.date != schedule_date:
            continue
        start = time_to_minutes(window.start_time)
        end = min(time_to_minutes(window.end_time), cutoff)
        if start < end:
            intervals.append((start, end))

    if not intervals:
        return []

    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def get_free_intervals(schedule_date: date) -> list[tuple[int, int]]:
    merged_availability = get_merged_availability_intervals(schedule_date)
    if not merged_availability:
        return []

    raw_busy = [
        (time_to_minutes(block.start_time), time_to_minutes(block.end_time))
        for block in time_blocks
        if block.date == schedule_date and block.type == "busy"
    ]
    merged_busy: list[tuple[int, int]] = []
    for start, end in sorted(raw_busy):
        if start >= end:
            continue
        if merged_busy and start <= merged_busy[-1][1]:
            merged_busy[-1] = (merged_busy[-1][0], max(merged_busy[-1][1], end))
        else:
            merged_busy.append((start, end))

    free_intervals: list[tuple[int, int]] = []
    for win_start, win_end in merged_availability:
        cursor = win_start
        for b_start, b_end in merged_busy:
            if b_end <= cursor or b_start >= win_end:
                continue
            if b_start > cursor:
                free_intervals.append((cursor, min(b_start, win_end)))
            cursor = max(cursor, min(b_end, win_end))
            if cursor >= win_end:
                break
        if cursor < win_end:
            free_intervals.append((cursor, win_end))

    return free_intervals


def interval_is_available(start: int, end: int, schedule_date: date) -> bool:
    for free_start, free_end in get_free_intervals(schedule_date):
        if free_start <= start and end <= free_end:
            return True
    return False


def conflicts_with_reserved(start: int, end: int, reserved_intervals: list[tuple[int, int]] | None) -> bool:
    if not reserved_intervals:
        return False
    for reserved_start, reserved_end in reserved_intervals:
        if start < reserved_end and end > reserved_start:
            return True
    return False


def find_task_slot(task_duration: int, schedule_date: date, reserved_intervals: list[tuple[int, int]] | None = None) -> int | None:
    for free_start, free_end in get_free_intervals(schedule_date):
        start_candidate = free_start
        while start_candidate + task_duration <= free_end:
            candidate_end = start_candidate + task_duration
            if not conflicts_with_reserved(start_candidate, candidate_end, reserved_intervals):
                return start_candidate
            start_candidate += 15
    return None


def available_minutes(schedule_date: date) -> int:
    return sum(end - start for start, end in get_free_intervals(schedule_date))


def build_reason_list(
    task: Task,
    energy_level: int | None = None,
    urgency: int = 0,
    probability: float = 0.5,
    is_today: bool = True,
    is_manual: bool = False,
) -> list[str]:
    reasons: list[str] = []
    if is_manual:
        reasons.append("Manual placement")
    if task.difficulty >= 4:
        reasons.append("High difficulty")
    if task.importance >= 4:
        reasons.append("High importance")
    if urgency >= 3:
        reasons.append("Deadline approaching")
    if not is_manual:
        if is_today and energy_level is not None:
            if abs(task.difficulty - energy_level) <= 1:
                reasons.append("Good energy match")
            elif task.difficulty > energy_level:
                reasons.append("Scheduled despite lower energy")
            else:
                reasons.append("Lower complexity fits current energy")
        elif not is_today:
            reasons.append("Readiness unknown for future date")
    if is_today and probability >= 0.7:
        reasons.append("Strong completion likelihood")
    elif is_today and probability < 0.4:
        reasons.append("Model confidence is still modest")
    return reasons[:4]


# Automatically initialize state on module import
init_state()
