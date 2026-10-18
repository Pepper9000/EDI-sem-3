from fastapi import APIRouter, HTTPException

from models.schemas import Energy, WearableData
from services import db
from services import state as state_module

router = APIRouter()


@router.post("/energy")
def set_energy(energy: Energy):
    try:
        db.set_setting(
            "current_energy", str(energy.level), db_path=state_module.active_db_path
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    state_module.current_energy = energy.level
    return {"message": "Energy level updated", "energy": state_module.current_energy}


@router.get("/energy")
def get_energy():
    return {"energy": state_module.current_energy}


@router.post("/wearable-data")
def add_wearable_data(data: WearableData):
    try:
        db.set_setting(
            "wearable_data", data.model_dump_json(), db_path=state_module.active_db_path
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    state_module.wearable_data = data
    return {"message": "Wearable data received successfully", "data": state_module.wearable_data}


@router.get("/wearable-data")
def get_wearable_data():
    if state_module.wearable_data is None:
        return {"message": "No wearable data available"}
    return state_module.wearable_data


@router.get("/biological-state")
def biological_state():
    return {
        "manual_energy": state_module.current_energy,
        "circadian_energy": state_module.circadian_energy(),
        "wearable_energy": state_module.wearable_energy(),
        "effective_energy": state_module.get_effective_energy(),
    }
