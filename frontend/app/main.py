"""Payment frontend FastAPI application."""

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api_client import close_http_client
from app.config import get_settings
from app.routers import approvals, payment

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("frontend")

app = FastAPI(title=settings.app_name)
app.include_router(payment.router)
app.include_router(approvals.router)

_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_cashdesk_dir = Path(__file__).parent / "cashdesk_static"
static_dir = Path(__file__).parent / "static"


@app.on_event("startup")
async def on_startup() -> None:
    logger.info(
        "Frontend starting | api_base_url=%s log_level=%s",
        settings.api_base_url,
        settings.log_level,
    )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await close_http_client()
    logger.info("Frontend shutdown complete")


@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    if request.url.path.startswith("/static") or request.url.path.startswith("/cashdesk"):
        return await call_next(request)
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    level = logging.WARNING if elapsed_ms >= 1500 else logging.INFO
    logger.log(
        level,
        "HTTP %s %s -> %s in %sms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
    return response


@app.get("/terms-and-conditions", include_in_schema=False)
async def terms_and_conditions(request: Request):
    return _templates.TemplateResponse("policy.html", {"request": request})


@app.get("/cashdesk", include_in_schema=False)
async def cashdesk_index() -> RedirectResponse:
    return RedirectResponse(url="/cashdesk/login/", status_code=307)


@app.get("/")
async def root() -> dict:
    settings = get_settings()
    payload = {
        "service": "finance-payment-frontend",
        "status": "running",
        "message": "Open a payment link: /payment/{token}",
        "health": "/health",
        "thank_you": "/payment/thank-you",
        "approvals": "/approvals/{token}",
        "terms_and_conditions": "/terms-and-conditions",
        "api_base_url": settings.api_base_url,
    }
    if _cashdesk_dir.is_dir() and (_cashdesk_dir / "login").is_dir():
        payload["cashdesk"] = "/cashdesk/login/"
    return payload


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "finance-payment-frontend"}


# Static mounts last so they do not shadow app routes.
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

if _cashdesk_dir.is_dir() and (_cashdesk_dir / "login").is_dir():
    app.mount(
        "/cashdesk",
        StaticFiles(directory=str(_cashdesk_dir), html=True),
        name="cashdesk",
    )
    logging.getLogger(__name__).info("Cash Desk mounted at /cashdesk from %s", _cashdesk_dir)
