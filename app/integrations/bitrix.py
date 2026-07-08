"""Bitrix24 integration — real stub and mock implementation."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.integrations.base import InvoiceReference, PaymentSummary

logger = logging.getLogger(__name__)


class MockBitrixClient:
    """Placeholder Bitrix client for prototype — logs actions and returns fake IDs."""

    MOCK_SALES_DEAL_BASE = 900001
    MOCK_FINANCE_DEAL_BASE = 900002
    MOCK_B2C_DEAL_BASE = 900003

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._mock_leads: dict[int, dict[str, Any]] = {}
        self._mock_deals: dict[int, dict[str, Any]] = {}

    def seed_lead(self, lead_id: int, *, email: str, name: str, amount: Decimal) -> None:
        self._mock_leads[lead_id] = {
            "ID": lead_id,
            "TITLE": f"Lead {lead_id}",
            "EMAIL": [{"VALUE": email, "VALUE_TYPE": "WORK"}],
            "NAME": name.split()[0] if name else "Customer",
            "LAST_NAME": " ".join(name.split()[1:]) if name and " " in name else "",
            "OPPORTUNITY": str(amount),
            "CURRENCY_ID": self.settings.default_currency,
            "STATUS_ID": self.settings.bitrix_lead_payment_stage_id,
        }

    async def get_lead(self, lead_id: int) -> dict[str, Any]:
        if lead_id in self._mock_leads:
            return self._mock_leads[lead_id]
        return {
            "ID": lead_id,
            "TITLE": f"Lead {lead_id}",
            "OPPORTUNITY": "10000.00",
            "CURRENCY_ID": self.settings.default_currency,
            "STATUS_ID": self.settings.bitrix_lead_payment_stage_id,
        }

    async def get_deal(self, deal_id: int) -> dict[str, Any]:
        if deal_id in self._mock_deals:
            return self._mock_deals[deal_id]
        return {"ID": deal_id, "TITLE": f"Deal {deal_id}", "STAGE_ID": "NEW"}

    async def convert_lead_to_sales_deal(self, lead_id: int, context: dict[str, Any]) -> int:
        deal_id = self.MOCK_SALES_DEAL_BASE + lead_id
        lead = await self.get_lead(lead_id)
        self._mock_deals[deal_id] = {
            "ID": deal_id,
            "TITLE": f"Sales Deal - {lead.get('TITLE', lead_id)}",
            "STAGE_ID": "NEW",
            "OPPORTUNITY": lead.get("OPPORTUNITY"),
            "CURRENCY_ID": lead.get("CURRENCY_ID"),
        }
        logger.info("[MockBitrix] Converted lead %s to sales deal %s", lead_id, deal_id)
        return deal_id

    async def create_finance_deal(self, lead_id: int, context: dict[str, Any]) -> int:
        deal_id = self.MOCK_FINANCE_DEAL_BASE + lead_id
        lead = await self.get_lead(lead_id)
        self._mock_deals[deal_id] = {
            "ID": deal_id,
            "TITLE": f"Finance Deal - {lead.get('TITLE', lead_id)}",
            "STAGE_ID": self.settings.bitrix_finance_generate_link_stage_id,
            "OPPORTUNITY": lead.get("OPPORTUNITY"),
            "CURRENCY_ID": lead.get("CURRENCY_ID"),
        }
        logger.info("[MockBitrix] Created finance deal %s for lead %s", deal_id, lead_id)
        return deal_id

    async def create_b2c_deal(self, lead_id: int, context: dict[str, Any]) -> int:
        deal_id = self.MOCK_B2C_DEAL_BASE + lead_id
        lead = await self.get_lead(lead_id)
        self._mock_deals[deal_id] = {
            "ID": deal_id,
            "TITLE": f"B2C Deal - {lead.get('TITLE', lead_id)}",
            "STAGE_ID": "NEW",
            "OPPORTUNITY": lead.get("OPPORTUNITY"),
            "CURRENCY_ID": lead.get("CURRENCY_ID"),
        }
        logger.info("[MockBitrix] Created B2C deal %s for lead %s", deal_id, lead_id)
        return deal_id

    async def attach_invoice_reference(self, deal_id: int, invoice: InvoiceReference) -> None:
        deal = await self.get_deal(deal_id)
        deal[self.settings.bitrix_field_invoice_reference] = invoice.invoice_number
        deal[self.settings.bitrix_field_invoice_url] = invoice.pdf_url or invoice.pdf_path
        self._mock_deals[deal_id] = deal
        logger.info(
            "[MockBitrix] Attached invoice %s to deal %s",
            invoice.invoice_id,
            deal_id,
        )

    async def update_deal_payment_summary(self, deal_id: int, summary: PaymentSummary) -> None:
        deal = await self.get_deal(deal_id)
        deal[self.settings.bitrix_field_total_amount] = str(summary.total_amount)
        deal[self.settings.bitrix_field_amount_paid] = str(summary.amount_paid)
        deal[self.settings.bitrix_field_remaining_balance] = str(summary.remaining_balance)
        self._mock_deals[deal_id] = deal
        logger.info("[MockBitrix] Updated payment summary on deal %s", deal_id)

    async def set_deal_payment_link(self, deal_id: int, payment_url: str) -> None:
        deal = await self.get_deal(deal_id)
        deal[self.settings.bitrix_field_payment_link] = payment_url
        self._mock_deals[deal_id] = deal
        logger.info("[MockBitrix] Set payment link on deal %s: %s", deal_id, payment_url)

    def extract_lead_amount(self, lead: dict[str, Any]) -> Decimal:
        opportunity = lead.get("OPPORTUNITY")
        if opportunity is not None and str(opportunity).strip():
            return Decimal(str(opportunity))
        return Decimal("0.00")

    def extract_customer_details(self, lead: dict[str, Any]) -> tuple[str | None, str | None]:
        emails = lead.get("EMAIL") or []
        email = emails[0].get("VALUE") if emails else lead.get("EMAIL")
        if isinstance(email, list) and email:
            email = email[0].get("VALUE")
        name_parts = [lead.get("NAME"), lead.get("LAST_NAME")]
        name = " ".join(p for p in name_parts if p).strip() or None
        return (str(email) if email else None, name)


class RealBitrixClient:
    """Real Bitrix24 REST client — replace mock when credentials are configured."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.bitrix24_webhook_url.rstrip("/") + "/"

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.settings.bitrix24_webhook_url:
            raise RuntimeError("BITRIX24_WEBHOOK_URL is not configured")

        url = f"{self.base_url}{method}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=params or {})
            response.raise_for_status()
            payload = response.json()

        if "error" in payload:
            raise RuntimeError(f"Bitrix API error: {payload.get('error_description', payload['error'])}")

        result = payload.get("result", payload)
        return result if isinstance(result, dict) else {"result": result}

    async def get_lead(self, lead_id: int) -> dict[str, Any]:
        return await self._call("crm.lead.get", {"id": lead_id})

    async def get_deal(self, deal_id: int) -> dict[str, Any]:
        return await self._call("crm.deal.get", {"id": deal_id})

    async def convert_lead_to_sales_deal(self, lead_id: int, context: dict[str, Any]) -> int:
        result = await self._call(
            "crm.lead.convert",
            {
                "id": lead_id,
                "params": {"DEAL": {"CATEGORY_ID": self.settings.bitrix_sales_pipeline_id or 0}},
            },
        )
        deal_ids = result.get("DEAL") or []
        if deal_ids:
            return int(deal_ids[0])
        raise RuntimeError(f"Lead conversion did not return deal ID for lead {lead_id}")

    async def create_finance_deal(self, lead_id: int, context: dict[str, Any]) -> int:
        lead = await self.get_lead(lead_id)
        fields = {
            "TITLE": f"Finance - {lead.get('TITLE', lead_id)}",
            "OPPORTUNITY": lead.get("OPPORTUNITY"),
            "CURRENCY_ID": lead.get("CURRENCY_ID") or self.settings.default_currency,
            "CATEGORY_ID": self.settings.bitrix_finance_pipeline_id or None,
        }
        result = await self._call("crm.deal.add", {"fields": {k: v for k, v in fields.items() if v is not None}})
        return int(result)

    async def create_b2c_deal(self, lead_id: int, context: dict[str, Any]) -> int:
        lead = await self.get_lead(lead_id)
        fields = {
            "TITLE": f"B2C - {lead.get('TITLE', lead_id)}",
            "OPPORTUNITY": lead.get("OPPORTUNITY"),
            "CURRENCY_ID": lead.get("CURRENCY_ID") or self.settings.default_currency,
            "CATEGORY_ID": self.settings.bitrix_b2c_pipeline_id or None,
        }
        result = await self._call("crm.deal.add", {"fields": {k: v for k, v in fields.items() if v is not None}})
        return int(result)

    async def attach_invoice_reference(self, deal_id: int, invoice: InvoiceReference) -> None:
        fields = {
            self.settings.bitrix_field_invoice_reference: invoice.invoice_number,
            self.settings.bitrix_field_invoice_url: invoice.pdf_url or invoice.pdf_path,
        }
        await self._call("crm.deal.update", {"id": deal_id, "fields": fields})

    async def update_deal_payment_summary(self, deal_id: int, summary: PaymentSummary) -> None:
        fields = {
            self.settings.bitrix_field_total_amount: str(summary.total_amount),
            self.settings.bitrix_field_amount_paid: str(summary.amount_paid),
            self.settings.bitrix_field_remaining_balance: str(summary.remaining_balance),
        }
        await self._call("crm.deal.update", {"id": deal_id, "fields": fields})

    async def set_deal_payment_link(self, deal_id: int, payment_url: str) -> None:
        if not self.settings.bitrix_field_payment_link:
            raise RuntimeError("BITRIX_FIELD_PAYMENT_LINK is not configured")
        await self._call(
            "crm.deal.update",
            {"id": deal_id, "fields": {self.settings.bitrix_field_payment_link: payment_url}},
        )
        logger.info("Set payment link on Bitrix deal %s", deal_id)

    def extract_lead_amount(self, lead: dict[str, Any]) -> Decimal:
        opportunity = lead.get("OPPORTUNITY")
        if opportunity is not None and str(opportunity).strip():
            return Decimal(str(opportunity))
        return Decimal("0.00")

    def extract_customer_details(self, lead: dict[str, Any]) -> tuple[str | None, str | None]:
        emails = lead.get("EMAIL") or []
        email = emails[0].get("VALUE") if emails else None
        name_parts = [lead.get("NAME"), lead.get("LAST_NAME")]
        name = " ".join(p for p in name_parts if p).strip() or None
        return (email, name)
