"""Finance Automation FastAPI application."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import dev, health, payment, webhooks

settings = get_settings()
logging.basicConfig(level=settings.log_level)

Path(settings.storage_path).mkdir(parents=True, exist_ok=True)
Path(settings.storage_path, "emails").mkdir(parents=True, exist_ok=True)
Path(settings.storage_path, "pdfs").mkdir(parents=True, exist_ok=True)

app = FastAPI(title=settings.app_name)
app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(payment.router)
app.include_router(dev.router)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
