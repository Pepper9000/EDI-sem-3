from pathlib import Path
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from routes.availability import router as availability_router
from routes.energy import router as energy_router
from routes.feedback import router as feedback_router
from routes.settings import router as settings_router
from routes.tasks import router as tasks_router
from services.scheduler import generate_schedule_payload

app = FastAPI(title="Chronos", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)
app.include_router(energy_router)
app.include_router(feedback_router)
app.include_router(availability_router)
app.include_router(settings_router)

frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
frontend_assets = frontend_dist / "assets"
if frontend_assets.is_dir():
    app.mount("/assets", StaticFiles(directory=frontend_assets), name="frontend-assets")


@app.get("/")
def home():
    frontend_index = frontend_dist / "index.html"
    if frontend_index.is_file():
        return FileResponse(frontend_index)
    return RedirectResponse(os.getenv("DAYPLAN_FRONTEND_URL", "http://127.0.0.1:5173"))


@app.get("/favicon.svg")
def favicon():
    favicon_path = frontend_dist / "favicon.svg"
    if favicon_path.is_file():
        return FileResponse(favicon_path)
    return {"message": "Frontend assets are not built"}


@app.get("/schedule")
def generate_schedule(date: str | None = None):
    return generate_schedule_payload(target_date_str=date)
