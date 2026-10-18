from fastapi import APIRouter, HTTPException

from ml.personalization import train_model
from models.schemas import Feedback
from services import db
from services import state as state_module

router = APIRouter()


@router.post("/feedback")
def add_feedback(feedback: Feedback):
    try:
        db.add_feedback(feedback, db_path=state_module.active_db_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    state_module.feedback_data.append(feedback)
    return {"message": "Feedback recorded successfully", "feedback": feedback}


@router.get("/feedback")
def get_feedback():
    return state_module.feedback_data


@router.delete("/feedback")
def clear_feedback():
    try:
        db.clear_feedback(db_path=state_module.active_db_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    state_module.feedback_data.clear()
    return {"message": "All feedback cleared"}


@router.get("/ml-status")
def get_ml_status():
    model = train_model()
    feedback_count = len(state_module.feedback_data)
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
