"""Development and testing helper endpoints."""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.config import get_settings
from app.integrations.factory import get_bitrix_client
from app.services.seed_mock_data import seed_mock_data
from app.services.workflow_orchestrator import WorkflowOrchestrator

router = APIRouter(prefix="/api/dev", tags=["dev"])


class SendPaymentLinkRequest(BaseModel):
    lead_id: int | None = None
    finance_deal_id: int | None = None
    customer_email: str | None = None
    customer_name: str | None = None
    total_amount: Decimal | None = Field(default=None, description="Optional total for new leads")


class SimulatePaymobRequest(BaseModel):
    token: str | None = None
    merchant_reference: str | None = None
    amount: Decimal | None = None


@router.post("/send-payment-link")
async def send_payment_link(
    body: SendPaymentLinkRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    orchestrator = WorkflowOrchestrator(db)

    if body.lead_id:
        override_kwargs: dict[str, Any] = {}
        if body.customer_email and body.customer_name and body.total_amount is not None:
            override_kwargs = {
                "customer_email": body.customer_email,
                "customer_name": body.customer_name,
                "total_amount": body.total_amount,
            }
        else:
            bitrix = get_bitrix_client()
            if hasattr(bitrix, "seed_lead") and body.customer_email:
                bitrix.seed_lead(
                    body.lead_id,
                    email=body.customer_email,
                    name=body.customer_name or "Test Customer",
                    amount=body.total_amount or Decimal("10000.00"),
                )
        session = await orchestrator.initiate_payment_from_lead(body.lead_id, **override_kwargs)
        return {
            "status": "ok",
            "source": "lead",
            "lead_id": body.lead_id,
            "token": session.token,
            "payment_url": orchestrator.session_service.build_payment_url(session.token),
            "merchant_reference": session.merchant_reference,
        }

    if body.finance_deal_id:
        try:
            session = await orchestrator.initiate_payment_from_finance_deal(body.finance_deal_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "status": "ok",
            "source": "finance_deal",
            "finance_deal_id": body.finance_deal_id,
            "token": session.token,
            "payment_url": orchestrator.session_service.build_payment_url(session.token),
            "merchant_reference": session.merchant_reference,
        }

    raise HTTPException(status_code=400, detail="Provide lead_id or finance_deal_id")


@router.post("/simulate-paymob-webhook")
async def simulate_paymob_webhook(
    body: SimulatePaymobRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not body.token and not body.merchant_reference:
        raise HTTPException(status_code=400, detail="Provide token or merchant_reference")

    orchestrator = WorkflowOrchestrator(db)
    try:
        workflow = await orchestrator.simulate_payment(
            token=body.token,
            merchant_reference=body.merchant_reference,
            amount=body.amount,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if workflow is None:
        return {"status": "duplicate", "reason": "transaction already processed"}

    return {
        "status": "ok",
        "workflow_id": workflow.id,
        "sales_deal_id": workflow.sales_deal_id,
        "finance_deal_id": workflow.finance_deal_id,
        "b2c_deal_id": workflow.b2c_deal_id,
        "zoho_invoice_id": workflow.zoho_invoice_id,
        "amount_paid": str(workflow.amount_paid),
        "remaining_balance": str(workflow.remaining_balance),
        "payment_status": workflow.payment_status,
        "payment_percentage": str(workflow.payment_percentage()),
        "reminders_enabled": workflow.reminders_enabled,
    }


@router.post("/process-reminders")
async def process_reminders(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Manually run due payment reminders (also runs on the background scheduler)."""
    from app.services.reminder_service import ReminderService

    return await ReminderService(db).process_due_reminders()


@router.post("/seed-mock-data")
async def seed_mock_customers(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Seed mock customers with Paymob-shaped payment data for Supabase visualization."""
    return seed_mock_data(db)


class ZohoExchangeCodeRequest(BaseModel):
    code: str = Field(..., description="Authorization code returned by Zoho OAuth redirect")


@router.get("/zoho/status")
async def zoho_status() -> dict[str, Any]:
    """Check Zoho Books connection and list organizations when credentials work."""
    from app.integrations.factory import get_zoho_client
    from app.integrations.zoho import ZohoBooksApiError

    settings = get_settings()
    client = get_zoho_client(settings)
    try:
        result = await client.test_connection()
    except ZohoBooksApiError as exc:
        return {
            "ok": False,
            "mode": "live_error",
            "error_code": exc.code,
            "message": exc.message,
            "status_code": exc.status_code,
            "use_mock_integrations": settings.use_mock_integrations,
        }
    except Exception as exc:
        return {
            "ok": False,
            "mode": "error",
            "message": str(exc),
            "use_mock_integrations": settings.use_mock_integrations,
        }
    result["use_mock_integrations"] = settings.use_mock_integrations
    result["has_client_id"] = bool(settings.zoho_client_id)
    result["has_refresh_token"] = bool(settings.zoho_refresh_token)
    result["has_organization_id"] = bool(settings.zoho_organization_id)
    return result


@router.get("/zoho/oauth-url")
async def zoho_oauth_url(state: str = "zoho-books-connect") -> dict[str, Any]:
    """Build the Zoho OAuth authorize URL (open in browser to connect Books)."""
    from app.integrations.zoho import RealZohoBooksClient

    settings = get_settings()
    if settings.use_mock_integrations:
        raise HTTPException(
            status_code=400,
            detail="Set USE_MOCK_INTEGRATIONS=false before connecting real Zoho Books.",
        )
    try:
        client = RealZohoBooksClient(settings)
        url = client.build_authorization_url(state=state)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "authorization_url": url,
        "redirect_uri": settings.zoho_oauth_redirect_uri,
        "scopes": settings.zoho_oauth_scopes,
        "accounts_url": settings.zoho_accounts_url,
        "instructions": [
            "1. Register a Server-based client at https://api-console.zoho.com/ (or .ae for UAE).",
            "2. Add the same Redirect URI as ZOHO_OAUTH_REDIRECT_URI.",
            "3. Open authorization_url, approve access, copy ?code= from the redirect.",
            "4. POST /api/dev/zoho/exchange-code with that code.",
            "5. Put refresh_token into ZOHO_REFRESH_TOKEN on Railway.",
            "6. GET /api/dev/zoho/status and set ZOHO_ORGANIZATION_ID from organizations list.",
        ],
    }


@router.post("/zoho/exchange-code")
async def zoho_exchange_code(body: ZohoExchangeCodeRequest) -> dict[str, Any]:
    """Exchange Zoho authorization code for refresh_token (paste into Railway env)."""
    from app.integrations.zoho import RealZohoBooksClient, ZohoBooksApiError

    settings = get_settings()
    if settings.use_mock_integrations:
        raise HTTPException(
            status_code=400,
            detail="Set USE_MOCK_INTEGRATIONS=false before connecting real Zoho Books.",
        )
    client = RealZohoBooksClient(settings)
    try:
        tokens = await client.exchange_authorization_code(body.code)
    except (RuntimeError, ZohoBooksApiError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    orgs: list[dict[str, Any]] = []
    org_error = None
    try:
        orgs = await client.list_organizations()
    except Exception as exc:
        org_error = str(exc)

    return {
        "ok": True,
        "refresh_token": tokens["refresh_token"],
        "expires_in": tokens.get("expires_in"),
        "api_domain": tokens.get("api_domain"),
        "organizations": orgs,
        "organization_list_error": org_error,
        "next_steps": [
            "Set ZOHO_REFRESH_TOKEN to refresh_token on Railway (keep secret).",
            "Set ZOHO_ORGANIZATION_ID from organizations[].organization_id.",
            "If api_domain suggests .ae/.eu, set ZOHO_ACCOUNTS_URL and ZOHO_BOOKS_API_URL for that DC.",
            "Redeploy backend, then GET /api/dev/zoho/status.",
        ],
    }


@router.get("/zoho/oauth-callback")
async def zoho_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Landing page for Zoho OAuth redirect — shows the code to exchange next."""
    if error:
        return {"ok": False, "error": error, "state": state}
    if not code:
        return {
            "ok": False,
            "message": "Missing code. Use /api/dev/zoho/oauth-url to start OAuth again.",
        }
    return {
        "ok": True,
        "code": code,
        "state": state,
        "next": "POST /api/dev/zoho/exchange-code with JSON {\"code\": \"...\"}",
    }


@router.get("/zoho/organizations")
async def zoho_organizations() -> dict[str, Any]:
    """List Zoho Books organizations for the connected refresh token."""
    from app.integrations.factory import get_zoho_client
    from app.integrations.zoho import ZohoBooksApiError

    client = get_zoho_client()
    try:
        orgs = await client.list_organizations()
    except (RuntimeError, ZohoBooksApiError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"organizations": orgs}
