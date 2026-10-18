from datetime import date, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
    task_id: int | None = None
    energy: int = Field(ge=1, le=5)
    difficulty: int = Field(ge=1, le=5)
    duration: int = Field(gt=0)
    completed: bool
    on_time: bool | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    completion_status: Literal["completed", "partial", "skipped"] | None = None
    difficulty_feedback: Literal["too_easy", "about_right", "too_hard"] | None = None
    timing_feedback: Literal["too_early", "good_time", "too_late"] | None = None
    energy_impact: Literal["energized", "same", "drained"] | None = None


class TimeBlock(BaseModel):
    date: date
    start_time: str
    end_time: str
    type: str = "busy"


class Availability(BaseModel):
    date: date
    start_time: str
    end_time: str


class EndOfDaySetting(BaseModel):
    end_of_day: str = "22:00"

    @field_validator("end_of_day")
    @classmethod
    def validate_end_of_day(cls, value: str) -> str:
        try:
            parsed = time.fromisoformat(value)
        except ValueError as error:
            raise ValueError("End of day must be a valid HH:MM time") from error
        if parsed.strftime("%H:%M") != value or value < "17:00":
            raise ValueError("End of day must be between 17:00 and 23:59")
        return value


class WearableData(BaseModel):
    sleep_hours: float = Field(ge=0, le=24)
    resting_heart_rate: int = Field(gt=0)
    hrv: float = Field(ge=0)
    steps: int = Field(ge=0)
    active_minutes: int = Field(ge=0)


class RescheduleTaskRequest(BaseModel):
    date: date
    start_time: str

