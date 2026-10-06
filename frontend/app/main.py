"""Payment frontend FastAPI application."""

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
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
# Compress HTML and the Finance JS/CSS bundles.
app.add_middleware(GZipMiddleware, minimum_size=1024)
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
    if request.url.path.startswith("/finance/_next/static/"):
        # Next.js hashes these filenames, so browsers can keep them for a year
        # instead of re-asking on every page open.
        response = await call_next(request)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
    if request.url.path.startswith("/static") or request.url.path.startswith("/finance"):
        response = await call_next(request)
        if request.url.path.startswith("/finance") and response.status_code == 200:
            # HTML shells must always be re-checked so a new deploy shows up.
            response.headers["Cache-Control"] = "no-cache"
        return response
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


def _legacy_cashdesk_target(rest: str = "") -> str:
    suffix = (rest or "").strip("/")
    if not suffix:
        return "/finance/login/"
    leaf = suffix.rsplit("/", 1)[-1]
    if "." in leaf:
        return f"/finance/{suffix}"
    return f"/finance/{suffix}/"


@app.get("/finance", include_in_schema=False)
async def finance_index() -> RedirectResponse:
    return RedirectResponse(url="/finance/login/", status_code=307)


@app.get("/cashdesk", include_in_schema=False)
@app.get("/cashdesk/{rest:path}", include_in_schema=False)
async def legacy_cashdesk(rest: str = "") -> RedirectResponse:
    """Old Cash Desk links keep working after the app moved to /finance."""
    return RedirectResponse(url=_legacy_cashdesk_target(rest), status_code=307)


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
        payload["finance"] = "/finance/login/"
    return payload


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "finance-payment-frontend"}


# Static mounts last so they do not shadow app routes.
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

if _cashdesk_dir.is_dir() and (_cashdesk_dir / "login").is_dir():
    app.mount(
        "/finance",
        StaticFiles(directory=str(_cashdesk_dir), html=True),
        name="finance",
    )
    logging.getLogger(__name__).info("Finance app mounted at /finance from %s", _cashdesk_dir)
