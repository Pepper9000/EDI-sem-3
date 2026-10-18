import json
import os
from pathlib import Path
import sqlite3
from typing import Any
from datetime import date

from models.schemas import Availability, Feedback, Task, TimeBlock, WearableData


def get_default_db_path() -> Path:
    env_path = os.getenv("DAYPLAN_DB_PATH")
    if env_path:
        return Path(env_path).resolve()
    return Path(__file__).resolve().parent.parent.parent / "data" / "dayplan.db"


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    target_path = Path(db_path).resolve() if db_path else get_default_db_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 5),
                    duration INTEGER NOT NULL CHECK(duration > 0),
                    importance INTEGER NOT NULL CHECK(importance BETWEEN 1 AND 5),
                    deadline TEXT
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS manual_placements (
                    task_id INTEGER PRIMARY KEY,
                    date TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS availability (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    UNIQUE(date, start_time, end_time)
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS time_blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'busy',
                    UNIQUE(date, start_time, end_time, type)
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_name TEXT NOT NULL,
                    task_id INTEGER,
                    energy INTEGER NOT NULL,
                    difficulty INTEGER NOT NULL,
                    duration INTEGER NOT NULL,
                    actual_duration INTEGER,
                    completed INTEGER NOT NULL,
                    on_time INTEGER,
                    rating INTEGER,
                    completion_status TEXT,
                    difficulty_feedback TEXT,
                    timing_feedback TEXT,
                    energy_impact TEXT,
                    importance INTEGER
                );
            """)

            # Ensure columns exist if table was already created in an existing database
            cursor = conn.execute("PRAGMA table_info(feedback)")
            columns = {row["name"] for row in cursor.fetchall()}
            if "actual_duration" not in columns:
                conn.execute("ALTER TABLE feedback ADD COLUMN actual_duration INTEGER;")
            if "importance" not in columns:
                conn.execute("ALTER TABLE feedback ADD COLUMN importance INTEGER;")
    finally:
        conn.close()


def load_all(db_path: Path | str | None = None) -> dict[str, Any]:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        # Load tasks
        cursor = conn.execute("SELECT id, name, difficulty, duration, importance, deadline FROM tasks ORDER BY id")
        tasks: list[Task] = []
        for row in cursor.fetchall():
            d_val = date.fromisoformat(row["deadline"]) if row["deadline"] else None
            tasks.append(
                Task(
                    id=row["id"],
                    name=row["name"],
                    difficulty=row["difficulty"],
                    duration=row["duration"],
                    importance=row["importance"],
                    deadline=d_val,
                )
            )

        # Load manual_placements
        cursor = conn.execute("SELECT task_id, date, start_time FROM manual_placements")
        manual_placements: dict[int, dict] = {}
        for row in cursor.fetchall():
            manual_placements[row["task_id"]] = {
                "date": date.fromisoformat(row["date"]),
                "start_time": row["start_time"],
            }

        # Load availability
        cursor = conn.execute("SELECT date, start_time, end_time FROM availability ORDER BY date, start_time")
        availability: list[Availability] = []
        for row in cursor.fetchall():
            availability.append(
                Availability(
                    date=date.fromisoformat(row["date"]),
                    start_time=row["start_time"],
                    end_time=row["end_time"],
                )
            )

        # Load time_blocks
        cursor = conn.execute("SELECT date, start_time, end_time, type FROM time_blocks ORDER BY date, start_time")
        time_blocks: list[TimeBlock] = []
        for row in cursor.fetchall():
            time_blocks.append(
                TimeBlock(
                    date=date.fromisoformat(row["date"]),
                    start_time=row["start_time"],
                    end_time=row["end_time"],
                    type=row["type"],
                )
            )

        # Load settings
        cursor = conn.execute("SELECT key, value FROM settings")
        settings: dict[str, Any] = {}
        for row in cursor.fetchall():
            settings[row["key"]] = row["value"]

        parsed_settings: dict[str, Any] = {
            "current_energy": int(settings.get("current_energy", 3)),
            "end_of_day": settings.get("end_of_day", "22:00"),
            "wearable_data": None,
        }
        if "wearable_data" in settings and settings["wearable_data"]:
            try:
                parsed_settings["wearable_data"] = WearableData.model_validate_json(settings["wearable_data"])
            except Exception:
                parsed_settings["wearable_data"] = None

        # Load feedback
        cursor = conn.execute("""
            SELECT task_name, task_id, energy, difficulty, duration,
                   actual_duration, completed, on_time, rating, completion_status,
                   difficulty_feedback, timing_feedback, energy_impact, importance
            FROM feedback ORDER BY id
        """)
        feedback: list[Feedback] = []
        for row in cursor.fetchall():
            feedback.append(
                Feedback(
                    task_name=row["task_name"],
                    task_id=row["task_id"],
                    energy=row["energy"],
                    difficulty=row["difficulty"],
                    duration=row["duration"],
                    actual_duration=row["actual_duration"],
                    completed=bool(row["completed"]),
                    on_time=None if row["on_time"] is None else bool(row["on_time"]),
                    rating=row["rating"],
                    completion_status=row["completion_status"],
                    difficulty_feedback=row["difficulty_feedback"],
                    timing_feedback=row["timing_feedback"],
                    energy_impact=row["energy_impact"],
                    importance=row["importance"],
                )
            )

        next_task_id = max((t.id for t in tasks if t.id is not None), default=0) + 1

        return {
            "tasks": tasks,
            "manual_placements": manual_placements,
            "availability": availability,
            "time_blocks": time_blocks,
            "settings": parsed_settings,
            "feedback": feedback,
            "next_task_id": next_task_id,
        }
    finally:
        conn.close()


def add_task(task: Task, db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO tasks (id, name, difficulty, duration, importance, deadline)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    difficulty=excluded.difficulty,
                    duration=excluded.duration,
                    importance=excluded.importance,
                    deadline=excluded.deadline
                """,
                (
                    task.id,
                    task.name,
                    task.difficulty,
                    task.duration,
                    task.importance,
                    str(task.deadline) if task.deadline else None,
                ),
            )
    finally:
        conn.close()


def delete_task(task_id: int, db_path: Path | str | None = None) -> bool:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM manual_placements WHERE task_id = ?", (task_id,))
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cursor.rowcount > 0
    finally:
        conn.close()


def clear_tasks(db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM manual_placements")
            conn.execute("DELETE FROM tasks")
    finally:
        conn.close()


def save_manual_placement(
    task_id: int, target_date: date, start_time: str, db_path: Path | str | None = None
) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO manual_placements (task_id, date, start_time)
                VALUES (?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    date=excluded.date,
                    start_time=excluded.start_time
                """,
                (
                    task_id,
                    str(target_date),
                    start_time,
                ),
            )
    finally:
        conn.close()


def delete_manual_placement(task_id: int, db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM manual_placements WHERE task_id = ?", (task_id,))
    finally:
        conn.close()


def add_availability(window: Availability, db_path: Path | str | None = None) -> bool:
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO availability (date, start_time, end_time)
                VALUES (?, ?, ?)
                """,
                (
                    str(window.date),
                    window.start_time,
                    window.end_time,
                ),
            )
            return cursor.rowcount > 0
    finally:
        conn.close()


def add_availability_batch(
    windows: list[Availability], db_path: Path | str | None = None
) -> int:
    if not windows:
        return 0
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.executemany(
                """
                INSERT OR IGNORE INTO availability (date, start_time, end_time)
                VALUES (?, ?, ?)
                """,
                [(str(w.date), w.start_time, w.end_time) for w in windows],
            )
            return cursor.rowcount
    finally:
        conn.close()


def delete_availability_window(
    date_str: str, start_time: str, end_time: str, db_path: Path | str | None = None
) -> bool:
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                "DELETE FROM availability WHERE date = ? AND start_time = ? AND end_time = ?",
                (date_str, start_time, end_time),
            )
            return cursor.rowcount > 0
    finally:
        conn.close()


def clear_availability(db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM availability")
    finally:
        conn.close()


def add_time_block(block: TimeBlock, db_path: Path | str | None = None) -> bool:
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO time_blocks (date, start_time, end_time, type)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(block.date),
                    block.start_time,
                    block.end_time,
                    block.type,
                ),
            )
            return cursor.rowcount > 0
    finally:
        conn.close()


def clear_time_blocks(db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM time_blocks")
    finally:
        conn.close()


def set_setting(key: str, value: str, db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
    finally:
        conn.close()


def add_feedback(fb: Feedback, db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO feedback (
                    task_name, task_id, energy, difficulty, duration,
                    actual_duration, completed, on_time, rating, completion_status,
                    difficulty_feedback, timing_feedback, energy_impact, importance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fb.task_name,
                    fb.task_id,
                    fb.energy,
                    fb.difficulty,
                    fb.duration,
                    fb.actual_duration,
                    1 if fb.completed else 0,
                    None if fb.on_time is None else (1 if fb.on_time else 0),
                    fb.rating,
                    fb.completion_status,
                    fb.difficulty_feedback,
                    fb.timing_feedback,
                    fb.energy_impact,
                    fb.importance,
                ),
            )
    finally:
        conn.close()


def clear_feedback(db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM feedback")
    finally:
        conn.close()
