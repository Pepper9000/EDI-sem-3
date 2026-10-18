from fastapi import APIRouter

from models.schemas import EndOfDaySetting
from services import state as state_module

router = APIRouter()


@router.get("/settings")
def get_settings():
    return {"end_of_day": state_module.end_of_day}


@router.put("/settings")
def update_settings(setting: EndOfDaySetting):
    state_module.end_of_day = setting.end_of_day
    return {"message": "Settings updated", "end_of_day": state_module.end_of_day}