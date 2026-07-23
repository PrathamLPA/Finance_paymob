"""Finance Automation FastAPI application (API / webhooks service)."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import dev, health, payment_api, webhooks

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

Path(settings.storage_path).mkdir(parents=True, exist_ok=True)
Path(settings.storage_path, "emails").mkdir(parents=True, exist_ok=True)
Path(settings.storage_path, "pdfs").mkdir(parents=True, exist_ok=True)


async def _reminder_scheduler_loop() -> None:
    """Periodically process payment reminders while the API is running."""
    from app.db.session import SessionLocal
    from app.services.reminder_service import ReminderService

    poll = max(30, settings.reminder_scheduler_poll_seconds)
    while True:
        try:
            db = SessionLocal()
            try:
                result = await ReminderService(db).process_due_reminders()
                if result.get("sent"):
                    logger.info("Reminder scheduler: %s", result)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder scheduler iteration failed")
        await asyncio.sleep(poll)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task: asyncio.Task | None = None
    if settings.reminder_enabled and settings.reminder_scheduler_enabled:
        task = asyncio.create_task(_reminder_scheduler_loop())
        logger.info(
            "Payment reminder scheduler started (every %ss, interval %sh)",
            settings.reminder_scheduler_poll_seconds,
            settings.reminder_interval_hours,
        )
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title=settings.app_name, lifespan=lifespan)

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
