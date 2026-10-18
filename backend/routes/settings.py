from fastapi import APIRouter, HTTPException

from models.schemas import EndOfDaySetting
from services import db
from services import state as state_module

router = APIRouter()


@router.get("/settings")
def get_settings():
    return {"end_of_day": state_module.end_of_day}


@router.put("/settings")
def update_settings(setting: EndOfDaySetting):
    try:
        db.set_setting("end_of_day", setting.end_of_day, db_path=state_module.active_db_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    state_module.end_of_day = setting.end_of_day
    return {"message": "Settings updated", "end_of_day": state_module.end_of_day}