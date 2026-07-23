"""Payment frontend FastAPI application."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import payment

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title=settings.app_name)
app.include_router(payment.router)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root() -> dict:
    settings = get_settings()
    return {
        "service": "finance-payment-frontend",
        "status": "running",
        "message": "Open a payment link: /payment/{token}",
        "health": "/health",
        "thank_you": "/payment/thank-you",
        "api_base_url": settings.api_base_url,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "finance-payment-frontend"}
