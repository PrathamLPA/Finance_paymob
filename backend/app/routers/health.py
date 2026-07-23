"""Health and root info endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/")
async def root() -> dict:
    settings = get_settings()
    return {
        "service": "finance-automation-api",
        "status": "running",
        "message": "This is the API service. Customer payment pages live on the frontend.",
        "health": "/health",
        "ready": "/ready",
        "bitrix_webhook": "/webhooks/bitrix24",
        "frontend_base_url": settings.payment_frontend_base_url,
        "docs": "/docs",
    }


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "finance-automation"}


@router.get("/ready")
async def ready(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    checks: dict[str, str] = {"api": "ok"}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc.__class__.__name__}"

    if settings.use_mock_integrations:
        checks["integrations"] = "mock"
    elif settings.paymob_secret_key and settings.bitrix24_webhook_url:
        checks["integrations"] = "live"
    else:
        checks["integrations"] = "incomplete"

    checks["payment_required_percent"] = str(settings.payment_required_percent)
    checks["reminders"] = "enabled" if settings.reminder_enabled else "disabled"
    if settings.zoho_refresh_token and not settings.use_mock_integrations:
        checks["zoho"] = "configured"
    else:
        checks["zoho"] = "mock_or_unset"

    ok = checks.get("database") == "ok"
    return {"status": "ready" if ok else "degraded", "checks": checks}
