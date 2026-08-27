"""Finance Automation FastAPI application (API / webhooks service)."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import approval_api, cash_api, dev, health, payment_api, staff_auth, webhooks

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
# Bitrix polls us constantly; one httpx line per lead fetch drowns real events.
logging.getLogger("httpx").setLevel(logging.WARNING)
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
    logger.info(
        "API starting environment=%s commit=%s mock_integrations=%s reminder_scheduler=%s "
        "paymob_hmac_fallback=%s",
        settings.app_env,
        (settings.railway_git_commit_sha or "unknown")[:8],
        settings.use_mock_integrations,
        settings.reminder_enabled and settings.reminder_scheduler_enabled,
        settings.paymob_hmac_fallback_to_inquiry,
    )
    try:
        from app.db.session import SessionLocal
        from app.services.staff_auth import bootstrap_manager_if_needed

        db = SessionLocal()
        try:
            created = bootstrap_manager_if_needed(db, settings)
            if created:
                logger.info("Cash Desk bootstrap manager ready email=%s", created.email)
            elif (settings.staff_bootstrap_manager_email or "").strip():
                logger.info(
                    "Cash Desk bootstrap manager email=%s (existing manager kept if different)",
                    settings.staff_bootstrap_manager_email.strip().lower(),
                )
        finally:
            db.close()
    except Exception:
        logger.exception("Cash Desk manager bootstrap skipped/failed")

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
        logger.info("API shutdown complete")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

origins = [o.strip() for o in settings.frontend_origin.split(",") if o.strip()]
for extra in (settings.cashdesk_origin or "").split(","):
    o = extra.strip()
    if o and o not in origins:
        origins.append(o)
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
app.include_router(approval_api.router)
app.include_router(staff_auth.router)
app.include_router(cash_api.router)
app.include_router(dev.router)
