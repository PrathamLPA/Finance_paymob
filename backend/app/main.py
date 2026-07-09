"""Finance Automation FastAPI application (API / webhooks service)."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import dev, health, payment_api, webhooks

settings = get_settings()
logging.basicConfig(level=settings.log_level)

Path(settings.storage_path).mkdir(parents=True, exist_ok=True)
Path(settings.storage_path, "emails").mkdir(parents=True, exist_ok=True)
Path(settings.storage_path, "pdfs").mkdir(parents=True, exist_ok=True)

app = FastAPI(title=settings.app_name)

origins = [o.strip() for o in settings.frontend_origin.split(",") if o.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(payment_api.router)
app.include_router(dev.router)
