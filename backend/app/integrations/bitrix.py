"""Bitrix24 integration — real stub and mock implementation."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.integrations.base import InvoiceReference, PaymentSummary

logger = logging.getLogger(__name__)

# Scopes an inbound webhook needs, per feature, for the error hints below.
SCOPE_HINTS = {
    "catalog.": "catalog",
    "im.": "im",
    "mail.": "mail",
    "user.": "user",
    "crm.": "crm",
}


class BitrixApiError(RuntimeError):
    """A Bitrix REST call failed; carries the reason Bitrix put in the body."""

    def __init__(self, method: str, *, status_code: int, code: str, description: str):
        self.method = method
        self.status_code = status_code
        self.code = code
        self.description = description
        super().__init__(f"{method} failed ({status_code} {code}): {description}")

    @property
    def missing_scope(self) -> str | None:
        """Best-guess scope to tick on the webhook, when this looks like a permission gap."""
        permissionish = {
            "insufficient_scope",
            "access_denied",
            "error_method_not_found",
            "method_not_found",
            "http_error",
        }
        if self.code.lower() not in permissionish and self.status_code not in (401, 403, 404):
            return None
        for prefix, scope in SCOPE_HINTS.items():
            if self.method.startswith(prefix):
                return scope
        return None


def extract_amount(entity: dict[str, Any], fallback_field: str = "") -> Decimal:
    """Read OPPORTUNITY, falling back to a configured custom amount field."""
    candidates = [entity.get("OPPORTUNITY")]
    if fallback_field:
        candidates.append(entity.get(fallback_field))

    for candidate in candidates:
        if candidate is None or not str(candidate).strip():
            continue
        try:
            return Decimal(str(candidate).replace(",", "").strip())
        except (ArithmeticError, ValueError):
            logger.warning("Could not parse Bitrix amount value %r", candidate)
    return Decimal("0.00")


def _lookup_field(entity: dict[str, Any], field_code: str) -> Any:
    if not field_code:
        return None
    if field_code in entity:
        return entity.get(field_code)
    lowered = {str(k).lower(): v for k, v in entity.items()}
    return lowered.get(field_code.lower())


def coerce_email(raw: Any) -> str | None:
    if raw in (None, "", [], {}):
        return None
    if isinstance(raw, str):
        value = raw.replace(";", ",").split(",")[0].strip()
        return value or None
    if isinstance(raw, dict):
        return coerce_email(raw.get("VALUE") or raw.get("value") or raw.get("EMAIL"))
    if isinstance(raw, (list, tuple)):
        for item in raw:
            email = coerce_email(item)
            if email:
                return email
    return None


def parse_lead_customer_details(
    lead: dict[str, Any],
    *,
    client_email_field: str = "",
    fallback_email_field: str = "",
) -> tuple[str | None, str | None]:
    """Name from NAME/LAST_NAME; email prefers the client UF field, then EMAIL."""
    name_parts = [lead.get("NAME"), lead.get("LAST_NAME")]
    name = " ".join(p for p in name_parts if p).strip() or None
    email = coerce_email(_lookup_field(lead, client_email_field)) if client_email_field else None
    if not email and fallback_email_field:
        email = coerce_email(_lookup_field(lead, fallback_email_field))
    if not email:
        email = coerce_email(lead.get("EMAIL"))
    return (email, name)


class MockBitrixClient:
    """Placeholder Bitrix client for prototype — logs actions and returns fake IDs."""

    MOCK_SALES_DEAL_BASE = 900001
    MOCK_FINANCE_DEAL_BASE = 900002
    MOCK_B2C_DEAL_BASE = 900003
    MOCK_ESTIMATE_BASE = 700000

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._mock_leads: dict[int, dict[str, Any]] = {}
        self._mock_deals: dict[int, dict[str, Any]] = {}
        self._mock_comments: dict[tuple[str, int], list[dict[str, Any]]] = {}
        self._mock_product_rows: dict[tuple[str, int], list[dict[str, Any]]] = {}
        self._mock_catalog_prices: dict[int, Decimal] = {}
        self._mock_estimates: dict[int, dict[str, Any]] = {}
        self._mock_users: dict[int, dict[str, Any]] = {}
        self._mock_department_managers: dict[int, list[int]] = {}
        self._mock_mail_sent: list[dict[str, Any]] = []
        self._mock_notifications: list[dict[str, Any]] = []
        self._next_estimate_id = self.MOCK_ESTIMATE_BASE
        self.seed_user(101, email="agent@test.com", name="Sales Agent")

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
            "CONTACT_ID": None,
            "ASSIGNED_BY_ID": 101,
        }

    def seed_catalog_product(self, product_id: int, *, name: str, price: Decimal) -> None:
        self._mock_catalog_prices[product_id] = Decimal(str(price))
        setattr(self, f"_catalog_name_{product_id}", name)

    def seed_lead_products(self, lead_id: int, rows: list[dict[str, Any]]) -> None:
        self._mock_product_rows[("L", lead_id)] = [dict(row) for row in rows]

    def seed_user(
        self,
        user_id: int,
        *,
        email: str,
        name: str,
        department_ids: list[int] | None = None,
    ) -> None:
        parts = name.split()
        self._mock_users[user_id] = {
            "ID": user_id,
            "EMAIL": email,
            "NAME": parts[0] if parts else name,
            "LAST_NAME": " ".join(parts[1:]) if len(parts) > 1 else "",
            "UF_DEPARTMENT": department_ids or [],
            "ACTIVE": True,
        }

    def seed_department_manager(self, department_id: int, manager_user_id: int) -> None:
        self._mock_department_managers.setdefault(department_id, [])
        if manager_user_id not in self._mock_department_managers[department_id]:
            self._mock_department_managers[department_id].append(manager_user_id)

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

    async def get_lead_userfield_enum_map(self, field_name: str) -> dict[str, str]:
        """Mock Payment Mode enums including the live Cash ID 5774."""
        if not field_name:
            return {}
        return {
            "5774": "cash",
            "5786": "cash",
            "5788": "online",
            "5790": "bank_transfer",
            "5792": "purchase_order",
            "5794": "tabby",
            "5796": "others",
        }

    async def get_deal(self, deal_id: int) -> dict[str, Any]:
        if deal_id in self._mock_deals:
            return self._mock_deals[deal_id]
        return {"ID": deal_id, "TITLE": f"Deal {deal_id}", "STAGE_ID": "NEW"}

    async def convert_lead_to_sales_deal(self, lead_id: int, context: dict[str, Any]) -> int:
        deal_id = self.MOCK_SALES_DEAL_BASE + lead_id
        lead = await self.get_lead(lead_id)
        pipeline_id = str(self.settings.bitrix_sales_pipeline_id or "16")
        self._mock_deals[deal_id] = {
            "ID": deal_id,
            "TITLE": f"Sales Deal - {lead.get('TITLE', lead_id)}",
            "STAGE_ID": "NEW",
            "CATEGORY_ID": pipeline_id,
            "OPPORTUNITY": lead.get("OPPORTUNITY"),
            "CURRENCY_ID": lead.get("CURRENCY_ID"),
            "ASSIGNED_BY_ID": lead.get("ASSIGNED_BY_ID"),
            "LEAD_ID": lead_id,
        }
        lead["STATUS_ID"] = "CONVERTED"
        self._mock_leads[lead_id] = lead
        logger.info(
            "[MockBitrix] Converted lead %s to Sales pipeline %s deal %s",
            lead_id,
            pipeline_id,
            deal_id,
        )
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
        if summary.payment_percentage is not None and self.settings.bitrix_field_payment_percentage:
            deal[self.settings.bitrix_field_payment_percentage] = str(summary.payment_percentage)
        if summary.payment_status and self.settings.bitrix_field_payment_status:
            deal[self.settings.bitrix_field_payment_status] = summary.payment_status
        if summary.latest_transaction_id and self.settings.bitrix_field_transaction_id:
            deal[self.settings.bitrix_field_transaction_id] = summary.latest_transaction_id
        self._mock_deals[deal_id] = deal
        logger.info("[MockBitrix] Updated payment summary on deal %s", deal_id)

    async def set_deal_payment_link(self, deal_id: int, payment_url: str) -> None:
        deal = await self.get_deal(deal_id)
        deal[self.settings.bitrix_field_payment_link] = payment_url
        self._mock_deals[deal_id] = deal
        logger.info("[MockBitrix] Set payment link on deal %s: %s", deal_id, payment_url)

    async def add_timeline_comment(
        self,
        *,
        entity_type: str,
        entity_id: int,
        comment: str,
        files: list[tuple[str, bytes]] | None = None,
    ) -> int | None:
        comments = self._mock_comments.setdefault((entity_type.upper(), entity_id), [])
        comment_id = len(comments) + 1
        entry: dict[str, Any] = {"id": comment_id, "COMMENT": comment}
        if files:
            entry["FILES"] = [name for name, _ in files]
        comments.append(entry)
        logger.info(
            "[MockBitrix] Timeline comment on %s %s: %s files=%s",
            entity_type,
            entity_id,
            comment[:120],
            len(files or []),
        )
        return comment_id

    async def set_deal_stage(self, deal_id: int, stage_id: str) -> None:
        deal = await self.get_deal(deal_id)
        deal["STAGE_ID"] = stage_id
        self._mock_deals[deal_id] = deal
        logger.info("[MockBitrix] Set deal %s stage to %s", deal_id, stage_id)

    async def sync_deal_customer_details(
        self,
        deal_id: int,
        *,
        name: str | None,
        email: str | None,
        phone: str | None,
    ) -> None:
        deal = await self.get_deal(deal_id)
        if name and self.settings.bitrix_field_customer_name:
            deal[self.settings.bitrix_field_customer_name] = name
        if email and self.settings.bitrix_field_customer_email:
            deal[self.settings.bitrix_field_customer_email] = email
        if phone and self.settings.bitrix_field_customer_phone:
            deal[self.settings.bitrix_field_customer_phone] = phone
        self._mock_deals[deal_id] = deal
        logger.info("[MockBitrix] Synced customer details on deal %s", deal_id)

    async def list_product_rows(self, *, owner_type: str, owner_id: int) -> list[dict[str, Any]]:
        return list(self._mock_product_rows.get((owner_type.upper(), owner_id), []))

    async def get_catalog_min_price(self, product_id: int) -> Decimal | None:
        if product_id in self._mock_catalog_prices:
            return self._mock_catalog_prices[product_id]
        return None

    async def create_estimate(
        self,
        *,
        lead_id: int,
        title: str,
        currency: str,
        opportunity: Decimal,
        tax_value: Decimal,
        contact_id: int | None,
        product_rows: list[dict[str, Any]],
        comments: str = "",
    ) -> int:
        self._next_estimate_id += 1
        estimate_id = self._next_estimate_id
        self._mock_estimates[estimate_id] = {
            "id": estimate_id,
            "title": title,
            "leadId": lead_id,
            "contactId": contact_id,
            "currencyId": currency,
            "opportunity": str(opportunity),
            "taxValue": str(tax_value),
            "comments": comments,
        }
        self._mock_product_rows[("Q", estimate_id)] = [dict(row) for row in product_rows]
        logger.info(
            "[MockBitrix] Created estimate %s for lead %s opportunity=%s %s",
            estimate_id,
            lead_id,
            opportunity,
            currency,
        )
        return estimate_id

    async def update_estimate(
        self,
        estimate_id: int,
        *,
        currency: str,
        opportunity: Decimal,
        tax_value: Decimal,
        product_rows: list[dict[str, Any]],
        comments: str | None = None,
    ) -> None:
        estimate = self._mock_estimates.get(estimate_id)
        if estimate is None:
            estimate = {"id": estimate_id}
            self._mock_estimates[estimate_id] = estimate
        estimate["currencyId"] = currency
        estimate["opportunity"] = str(opportunity)
        estimate["taxValue"] = str(tax_value)
        if comments is not None:
            estimate["comments"] = comments
        self._mock_product_rows[("Q", estimate_id)] = [dict(row) for row in product_rows]
        logger.info(
            "[MockBitrix] Updated estimate %s opportunity=%s %s rows=%s",
            estimate_id,
            opportunity,
            currency,
            len(product_rows),
        )

    async def update_lead_fields(self, lead_id: int, fields: dict[str, Any]) -> None:
        lead = self._mock_leads.setdefault(lead_id, {"ID": lead_id})
        lead.update(fields)
        logger.info("[MockBitrix] Updated lead %s fields=%s", lead_id, list(fields))

    async def set_lead_product_rows(
        self, lead_id: int, product_rows: list[dict[str, Any]]
    ) -> None:
        self._mock_product_rows[("L", lead_id)] = [dict(row) for row in product_rows]
        logger.info(
            "[MockBitrix] Set lead %s product rows=%s", lead_id, len(product_rows)
        )

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        return self._mock_users.get(user_id)

    async def resolve_manager_for_user(self, user_id: int) -> dict[str, Any] | None:
        user = await self.get_user(user_id)
        if not user:
            return None
        departments = user.get("UF_DEPARTMENT") or []
        if not isinstance(departments, list):
            departments = [departments]
        for dept in departments:
            try:
                dept_id = int(dept)
            except (TypeError, ValueError):
                continue
            for manager_id in self._mock_department_managers.get(dept_id, []):
                if manager_id == user_id:
                    continue
                manager = await self.get_user(manager_id)
                if manager and manager.get("EMAIL"):
                    return manager
        return None

    async def send_mail(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        from_email: str | None = None,
    ) -> bool:
        sender = from_email or self.settings.bitrix_mail_from or "noreply@bitrix.local"
        self._mock_mail_sent.append(
            {"from": sender, "to": to_email, "subject": subject, "body": body}
        )
        logger.info("[MockBitrix] Mail '%s' to %s from %s", subject, to_email, sender)
        return True

    async def notify_user(self, *, user_id: int, message: str) -> bool:
        self._mock_notifications.append({"user_id": user_id, "message": message})
        logger.info("[MockBitrix] Notification to user %s", user_id)
        return True

    def extract_lead_amount(self, lead: dict[str, Any]) -> Decimal:
        return extract_amount(lead, self.settings.bitrix_field_lead_amount)

    def extract_customer_details(self, lead: dict[str, Any]) -> tuple[str | None, str | None]:
        return parse_lead_customer_details(
            lead,
            client_email_field=self.settings.bitrix_field_client_email,
            fallback_email_field=self.settings.bitrix_field_customer_email,
        )


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

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        # Bitrix returns the useful reason (insufficient_scope, ERROR_METHOD_NOT_FOUND…)
        # in the body, so never surface a bare HTTP status.
        if isinstance(payload, dict) and payload.get("error"):
            raise BitrixApiError(
                method,
                status_code=response.status_code,
                code=str(payload.get("error")),
                description=str(payload.get("error_description") or ""),
            )
        if response.is_error:
            raise BitrixApiError(
                method,
                status_code=response.status_code,
                code="http_error",
                description=response.text[:300],
            )

        result = payload.get("result", payload)
        return result if isinstance(result, dict) else {"result": result}

    @staticmethod
    def _scalar(result: dict[str, Any]) -> Any:
        """_call wraps non-dict REST results as {"result": value}; unwrap them."""
        if isinstance(result, dict) and set(result) == {"result"}:
            return result["result"]
        return result

    async def get_lead(self, lead_id: int) -> dict[str, Any]:
        return await self._call("crm.lead.get", {"id": lead_id})

    async def get_lead_userfield_enum_map(self, field_name: str) -> dict[str, str]:
        """Return {enum_id: label_lower} for a lead UF enumeration field (cached)."""
        if not field_name:
            return {}
        cache: dict[str, dict[str, str]] = getattr(self, "_uf_enum_cache", {})
        if not hasattr(self, "_uf_enum_cache"):
            self._uf_enum_cache = cache
        if field_name in cache:
            return cache[field_name]

        result = await self._call(
            "crm.lead.userfield.list",
            {"filter": {"FIELD_NAME": field_name}},
        )
        rows: Any = result
        if isinstance(result, dict) and "result" in result:
            rows = result.get("result")
        if not isinstance(rows, list):
            rows = [rows] if rows else []

        labels: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            for item in row.get("LIST") or []:
                if not isinstance(item, dict):
                    continue
                enum_id = str(item.get("ID") or "").strip()
                value = str(item.get("VALUE") or "").strip().lower()
                if enum_id and value:
                    labels[enum_id] = value

        cache[field_name] = labels
        logger.info(
            "Loaded Bitrix lead userfield enums | field=%s count=%s",
            field_name,
            len(labels),
        )
        return labels

    async def get_deal(self, deal_id: int) -> dict[str, Any]:
        return await self._call("crm.deal.get", {"id": deal_id})

    async def convert_lead_to_sales_deal(self, lead_id: int, context: dict[str, Any]) -> int:
        """Convert the lead into a deal on the Sales pipeline (CATEGORY_ID=16)."""
        pipeline_id = self._sales_pipeline_id()
        try:
            result = await self._call(
                "crm.lead.convert",
                {
                    "id": lead_id,
                    "params": {"DEAL": {"CATEGORY_ID": pipeline_id}},
                },
            )
            deal_ids = result.get("DEAL") or []
            if deal_ids:
                deal_id = int(deal_ids[0] if isinstance(deal_ids, list) else deal_ids)
                logger.info(
                    "Converted lead %s via crm.lead.convert to Sales deal %s pipeline=%s",
                    lead_id,
                    deal_id,
                    pipeline_id,
                )
                return deal_id
        except BitrixApiError as exc:
            if not self._is_missing_method(exc):
                raise
            logger.warning(
                "crm.lead.convert unavailable (%s) — creating Sales deal with crm.deal.add | lead_id=%s",
                exc.code,
                lead_id,
            )

        return await self._create_sales_deal_from_lead(lead_id, pipeline_id)

    def _sales_pipeline_id(self) -> int:
        raw = str(self.settings.bitrix_sales_pipeline_id or "16").strip()
        try:
            return int(raw)
        except ValueError:
            logger.warning("Invalid BITRIX_SALES_PIPELINE_ID=%r — using 16 (Sales)", raw)
            return 16

    @staticmethod
    def _is_missing_method(exc: BitrixApiError) -> bool:
        blob = f"{exc.code} {exc.description}".lower()
        return "not_found" in blob or "method not found" in blob

    async def _create_sales_deal_from_lead(self, lead_id: int, pipeline_id: int) -> int:
        lead = await self.get_lead(lead_id)
        fields: dict[str, Any] = {
            "TITLE": lead.get("TITLE") or f"Sales - Lead {lead_id}",
            "CATEGORY_ID": pipeline_id,
            "OPPORTUNITY": lead.get("OPPORTUNITY"),
            "CURRENCY_ID": lead.get("CURRENCY_ID") or self.settings.default_currency,
            "ASSIGNED_BY_ID": lead.get("ASSIGNED_BY_ID"),
            "LEAD_ID": lead_id,
        }
        contact_id = lead.get("CONTACT_ID")
        if contact_id not in (None, "", "0", 0):
            fields["CONTACT_ID"] = contact_id
        company_id = lead.get("COMPANY_ID")
        if company_id not in (None, "", "0", 0):
            fields["COMPANY_ID"] = company_id

        result = await self._call(
            "crm.deal.add",
            {"fields": {key: value for key, value in fields.items() if value not in (None, "")}},
        )
        deal_id = int(self._scalar(result))
        try:
            await self._call("crm.lead.update", {"id": lead_id, "fields": {"STATUS_ID": "CONVERTED"}})
        except Exception:
            logger.exception(
                "Sales deal %s created but lead %s could not be moved to CONVERTED (Complete lead)",
                deal_id,
                lead_id,
            )
        logger.info(
            "Created Sales deal %s from lead %s pipeline=%s (crm.deal.add fallback)",
            deal_id,
            lead_id,
            pipeline_id,
        )
        return deal_id

    async def create_finance_deal(self, lead_id: int, context: dict[str, Any]) -> int:
        lead = await self.get_lead(lead_id)
        fields = {
            "TITLE": f"Finance - {lead.get('TITLE', lead_id)}",
            "OPPORTUNITY": lead.get("OPPORTUNITY"),
            "CURRENCY_ID": lead.get("CURRENCY_ID") or self.settings.default_currency,
            "CATEGORY_ID": self.settings.bitrix_finance_pipeline_id or None,
        }
        result = await self._call("crm.deal.add", {"fields": {k: v for k, v in fields.items() if v is not None}})
        return int(self._scalar(result))

    async def create_b2c_deal(self, lead_id: int, context: dict[str, Any]) -> int:
        lead = await self.get_lead(lead_id)
        fields = {
            "TITLE": f"B2C - {lead.get('TITLE', lead_id)}",
            "OPPORTUNITY": lead.get("OPPORTUNITY"),
            "CURRENCY_ID": lead.get("CURRENCY_ID") or self.settings.default_currency,
            "CATEGORY_ID": self.settings.bitrix_b2c_pipeline_id or None,
        }
        result = await self._call("crm.deal.add", {"fields": {k: v for k, v in fields.items() if v is not None}})
        return int(self._scalar(result))

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
        if summary.payment_percentage is not None and self.settings.bitrix_field_payment_percentage:
            fields[self.settings.bitrix_field_payment_percentage] = str(summary.payment_percentage)
        if summary.payment_status and self.settings.bitrix_field_payment_status:
            fields[self.settings.bitrix_field_payment_status] = summary.payment_status
        if summary.latest_transaction_id and self.settings.bitrix_field_transaction_id:
            fields[self.settings.bitrix_field_transaction_id] = summary.latest_transaction_id
        await self._call("crm.deal.update", {"id": deal_id, "fields": fields})

    async def set_deal_payment_link(self, deal_id: int, payment_url: str) -> None:
        if not self.settings.bitrix_field_payment_link:
            raise RuntimeError("BITRIX_FIELD_PAYMENT_LINK is not configured")
        await self._call(
            "crm.deal.update",
            {"id": deal_id, "fields": {self.settings.bitrix_field_payment_link: payment_url}},
        )
        logger.info("Set payment link on Bitrix deal %s", deal_id)

    async def add_timeline_comment(
        self,
        *,
        entity_type: str,
        entity_id: int,
        comment: str,
        files: list[tuple[str, bytes]] | None = None,
    ) -> int | None:
        import base64

        fields: dict[str, Any] = {
            "ENTITY_TYPE": (
                "quote"
                if entity_type.strip().upper() == "QUOTE"
                else entity_type.strip().upper()
            ),
            "ENTITY_ID": entity_id,
            "COMMENT": comment,
        }
        if files:
            # Bitrix expects [[filename, base64content], ...]
            fields["FILES"] = [
                [name, base64.b64encode(data).decode("ascii")] for name, data in files
            ]
        result = await self._call(
            "crm.timeline.comment.add",
            {"fields": fields},
        )
        raw = self._scalar(result)
        try:
            comment_id = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            comment_id = None
        logger.info(
            "Added Bitrix timeline comment id=%s on %s %s files=%s",
            comment_id if comment_id is not None else "-",
            entity_type,
            entity_id,
            len(files or []),
        )
        return comment_id

    async def set_deal_stage(self, deal_id: int, stage_id: str) -> None:
        await self._call("crm.deal.update", {"id": deal_id, "fields": {"STAGE_ID": stage_id}})
        logger.info("Set Bitrix deal %s stage to %s", deal_id, stage_id)

    async def sync_deal_customer_details(
        self,
        deal_id: int,
        *,
        name: str | None,
        email: str | None,
        phone: str | None,
    ) -> None:
        fields: dict[str, Any] = {}
        if name and self.settings.bitrix_field_customer_name:
            fields[self.settings.bitrix_field_customer_name] = name
        if email and self.settings.bitrix_field_customer_email:
            fields[self.settings.bitrix_field_customer_email] = email
        if phone and self.settings.bitrix_field_customer_phone:
            fields[self.settings.bitrix_field_customer_phone] = phone
        if not fields:
            return
        await self._call("crm.deal.update", {"id": deal_id, "fields": fields})

    async def list_product_rows(self, *, owner_type: str, owner_id: int) -> list[dict[str, Any]]:
        result = await self._call(
            "crm.item.productrow.list",
            {
                "filter": {
                    "=ownerType": owner_type.upper(),
                    "=ownerId": owner_id,
                }
            },
        )
        rows = result.get("productRows") or result.get("result") or []
        if isinstance(rows, dict):
            rows = rows.get("productRows") or []
        return list(rows) if isinstance(rows, list) else []

    async def get_catalog_min_price(self, product_id: int) -> Decimal | None:
        """Resolve the catalog list/minimum price for a product id."""
        if product_id <= 0:
            return None

        # Prefer catalog.price.list (modern catalog module).
        try:
            listed = await self._call(
                "catalog.price.list",
                {
                    "filter": {"productId": product_id},
                    "select": ["id", "productId", "price", "currency", "catalogGroupId"],
                },
            )
            prices = listed.get("prices") or listed.get("result") or []
            if isinstance(prices, dict):
                prices = prices.get("prices") or []
            if isinstance(prices, list) and prices:
                amounts = []
                for item in prices:
                    raw = item.get("price") if isinstance(item, dict) else None
                    if raw is None:
                        continue
                    amounts.append(Decimal(str(raw).replace(",", "").strip()))
                if amounts:
                    return min(amounts)
        except BitrixApiError as exc:
            scope = exc.missing_scope
            logger.info(
                "catalog.price.list unavailable | product_id=%s reason=%s%s "
                "fallback=crm.product.get",
                product_id,
                exc.code,
                f" add_scope={scope}" if scope else "",
            )
        except Exception:
            logger.exception(
                "catalog.price.list failed for product_id=%s; falling back to crm.product.get",
                product_id,
            )

        # Fallback for portals still exposing the legacy CRM product API.
        try:
            product = await self._call("crm.product.get", {"id": product_id})
            raw = product.get("PRICE") or product.get("price")
            if raw is None or not str(raw).strip():
                return None
            return Decimal(str(raw).replace(",", "").strip())
        except Exception:
            logger.exception("crm.product.get failed for product_id=%s", product_id)
            return None

    async def create_estimate(
        self,
        *,
        lead_id: int,
        title: str,
        currency: str,
        opportunity: Decimal,
        tax_value: Decimal,
        contact_id: int | None,
        product_rows: list[dict[str, Any]],
        comments: str = "",
    ) -> int:
        fields: dict[str, Any] = {
            "title": title,
            "leadId": lead_id,
            "currencyId": currency,
            "opportunity": float(opportunity),
            "taxValue": float(tax_value),
            "isManualOpportunity": "Y",
            "opened": "Y",
            "comments": comments,
        }
        if contact_id:
            fields["contactId"] = contact_id

        created = await self._call(
            "crm.item.add",
            {
                "entityTypeId": 7,  # Estimate
                "fields": fields,
            },
        )
        item = created.get("item") or created
        estimate_id = int(item.get("id") or item.get("ID") or self._scalar(created))

        cleaned_rows = []
        for row in product_rows:
            cleaned = {k: v for k, v in row.items() if v is not None}
            cleaned_rows.append(cleaned)

        if cleaned_rows:
            await self._call(
                "crm.item.productrow.set",
                {
                    "ownerType": "Q",
                    "ownerId": estimate_id,
                    "productRows": cleaned_rows,
                },
            )

        logger.info(
            "Created Bitrix estimate %s for lead %s opportunity=%s %s",
            estimate_id,
            lead_id,
            opportunity,
            currency,
        )
        return estimate_id

    async def update_estimate(
        self,
        estimate_id: int,
        *,
        currency: str,
        opportunity: Decimal,
        tax_value: Decimal,
        product_rows: list[dict[str, Any]],
        comments: str | None = None,
    ) -> None:
        fields: dict[str, Any] = {
            "currencyId": currency,
            "opportunity": float(opportunity),
            "taxValue": float(tax_value),
            "isManualOpportunity": "Y",
        }
        if comments is not None:
            fields["comments"] = comments
        await self._call(
            "crm.item.update",
            {
                "entityTypeId": 7,
                "id": estimate_id,
                "fields": fields,
            },
        )
        cleaned_rows = []
        for row in product_rows:
            cleaned = {k: v for k, v in row.items() if v is not None}
            cleaned_rows.append(cleaned)
        if cleaned_rows:
            await self._call(
                "crm.item.productrow.set",
                {
                    "ownerType": "Q",
                    "ownerId": estimate_id,
                    "productRows": cleaned_rows,
                },
            )
        logger.info(
            "Updated Bitrix estimate %s opportunity=%s %s rows=%s",
            estimate_id,
            opportunity,
            currency,
            len(cleaned_rows),
        )

    async def update_lead_fields(self, lead_id: int, fields: dict[str, Any]) -> None:
        cleaned = {k: v for k, v in fields.items() if k and v is not None}
        if not cleaned:
            return
        await self._call("crm.lead.update", {"id": lead_id, "fields": cleaned})
        logger.info("Updated Bitrix lead %s fields=%s", lead_id, list(cleaned))

    async def set_lead_product_rows(
        self, lead_id: int, product_rows: list[dict[str, Any]]
    ) -> None:
        cleaned_rows = []
        for row in product_rows:
            cleaned = {k: v for k, v in row.items() if v is not None}
            # crm.lead.productrows.set uses uppercase legacy keys.
            legacy = {
                "PRODUCT_ID": cleaned.get("productId") or cleaned.get("PRODUCT_ID"),
                "PRICE": cleaned.get("price") if "price" in cleaned else cleaned.get("PRICE"),
                "QUANTITY": cleaned.get("quantity")
                if "quantity" in cleaned
                else cleaned.get("QUANTITY"),
                "TAX_RATE": cleaned.get("taxRate")
                if "taxRate" in cleaned
                else cleaned.get("TAX_RATE"),
                "TAX_INCLUDED": cleaned.get("taxIncluded")
                if "taxIncluded" in cleaned
                else cleaned.get("TAX_INCLUDED"),
            }
            cleaned_rows.append({k: v for k, v in legacy.items() if v is not None})
        await self._call(
            "crm.lead.productrows.set",
            {"id": lead_id, "rows": cleaned_rows},
        )
        logger.info("Set Bitrix lead %s product rows=%s", lead_id, len(cleaned_rows))

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        try:
            result = await self._call("user.get", {"ID": user_id})
        except BitrixApiError as exc:
            scope = exc.missing_scope
            logger.warning(
                "user.get unavailable | user_id=%s reason=%s%s",
                user_id,
                exc.code,
                f" add_scope={scope}" if scope else "",
            )
            return None
        users = result.get("result") if isinstance(result, dict) and "result" in result else result
        if isinstance(users, list) and users:
            return users[0] if isinstance(users[0], dict) else None
        if isinstance(users, dict) and users.get("ID"):
            return users
        # Some portals return the user object directly as the _call result.
        if isinstance(result, dict) and (result.get("ID") or result.get("EMAIL")):
            return result
        return None

    async def resolve_manager_for_user(self, user_id: int) -> dict[str, Any] | None:
        user = await self.get_user(user_id)
        if not user:
            return None
        departments = user.get("UF_DEPARTMENT") or []
        if not isinstance(departments, list):
            departments = [departments]
        dept_ids = []
        for dept in departments:
            try:
                dept_ids.append(int(dept))
            except (TypeError, ValueError):
                continue
        if not dept_ids:
            return None

        try:
            managers_by_dept = await self._call(
                "im.department.managers.get",
                {"ID": dept_ids, "USER_DATA": "Y"},
            )
        except BitrixApiError as exc:
            scope = exc.missing_scope
            logger.warning(
                "Manager lookup unavailable | user_id=%s departments=%s reason=%s%s",
                user_id,
                dept_ids,
                exc.code,
                f" add_scope={scope}" if scope else "",
            )
            return None
        except Exception:
            logger.exception("im.department.managers.get failed for user %s", user_id)
            return None

        raw = managers_by_dept.get("result") if isinstance(managers_by_dept, dict) else managers_by_dept
        if not isinstance(raw, dict):
            raw = managers_by_dept if isinstance(managers_by_dept, dict) else {}

        for _dept, managers in raw.items():
            if _dept in ("result", "time"):
                continue
            if not isinstance(managers, list):
                continue
            for manager in managers:
                if isinstance(manager, dict):
                    try:
                        mid = int(manager.get("id") or manager.get("ID") or 0)
                    except (TypeError, ValueError):
                        mid = 0
                    if mid == user_id:
                        continue
                    email = manager.get("email") or manager.get("EMAIL")
                    if email:
                        return {
                            "ID": mid,
                            "EMAIL": email,
                            "NAME": manager.get("first_name") or manager.get("NAME") or "",
                            "LAST_NAME": manager.get("last_name") or manager.get("LAST_NAME") or "",
                        }
                else:
                    try:
                        mid = int(manager)
                    except (TypeError, ValueError):
                        continue
                    if mid == user_id:
                        continue
                    fetched = await self.get_user(mid)
                    if fetched and fetched.get("EMAIL"):
                        return fetched
        return None

    async def send_mail(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        from_email: str | None = None,
    ) -> bool:
        """Send via Bitrix Mail. Returns False and logs a clear diagnosis on failure."""
        sender = (from_email or self.settings.bitrix_mail_from or "").strip()
        if not sender:
            try:
                senders = await self._call("mail.mailbox.senders", {})
                items = senders.get("result") if isinstance(senders, dict) else senders
                if isinstance(items, dict):
                    items = items.get("senders") or items.get("result") or []
                if isinstance(items, list) and items:
                    first = items[0]
                    if isinstance(first, dict):
                        sender = str(first.get("email") or first.get("EMAIL") or "")
                    else:
                        sender = str(first)
            except BitrixApiError as exc:
                logger.warning(
                    "FAIL Bitrix mail | step=list_senders to=%s reason=%s fix=%s detail=%s",
                    to_email,
                    exc.code,
                    _mail_fix_hint(exc),
                    (exc.description or "")[:200] or "-",
                )
            except Exception:
                logger.exception(
                    "FAIL Bitrix mail | step=list_senders to=%s reason=unexpected_error",
                    to_email,
                )
        if not sender:
            logger.error(
                "FAIL Bitrix mail | step=choose_from to=%s reason=no_from_address "
                "fix=set_BITRIX_MAIL_FROM_or_connect_Bitrix_mailbox "
                "detail=mail.mailbox.senders returned no sender and BITRIX_MAIL_FROM is empty",
                to_email,
            )
            return False

        try:
            result = await self._call(
                "mail.message.send",
                {
                    "from": sender,
                    "to": [to_email],
                    "subject": subject,
                    "body": body,
                },
            )
        except BitrixApiError as exc:
            logger.error(
                "FAIL Bitrix mail | step=send to=%s from=%s reason=%s fix=%s detail=%s",
                to_email,
                sender,
                exc.code,
                _mail_fix_hint(exc),
                (exc.description or "")[:200] or "-",
            )
            return False
        except Exception:
            logger.exception(
                "FAIL Bitrix mail | step=send to=%s from=%s reason=unexpected_error",
                to_email,
                sender,
            )
            return False

        success = True
        if isinstance(result, dict):
            if "success" in result:
                success = bool(result.get("success"))
            nested = result.get("result")
            if isinstance(nested, dict) and "success" in nested:
                success = bool(nested.get("success"))
        if success:
            logger.info(
                "OK Bitrix mail | to=%s from=%s subject=%s",
                to_email,
                sender,
                subject,
            )
        else:
            logger.error(
                "FAIL Bitrix mail | step=send to=%s from=%s reason=bitrix_rejected "
                "fix=check_mailbox_connected_and_BITRIX_MAIL_FROM_matches_a_sender "
                "detail=%s",
                to_email,
                sender,
                str(result)[:300],
            )
        return success

    async def notify_user(self, *, user_id: int, message: str) -> bool:
        """Bitrix chat notification — works when mail is not available to the webhook."""
        try:
            await self._call(
                "im.notify.system.add",
                {"USER_ID": user_id, "MESSAGE": message},
            )
        except BitrixApiError as exc:
            logger.warning(
                "FAIL Bitrix chat | user_id=%s reason=%s fix=%s detail=%s",
                user_id,
                exc.code,
                (
                    f"add_scope={exc.missing_scope}"
                    if exc.missing_scope
                    else "check_im_scope_and_user_id"
                ),
                (exc.description or "")[:200] or "-",
            )
            return False
        except Exception:
            logger.exception("FAIL Bitrix chat | user_id=%s reason=unexpected_error", user_id)
            return False
        logger.info("OK Bitrix chat | user_id=%s", user_id)
        return True

    def extract_lead_amount(self, lead: dict[str, Any]) -> Decimal:
        return extract_amount(lead, self.settings.bitrix_field_lead_amount)

    def extract_customer_details(self, lead: dict[str, Any]) -> tuple[str | None, str | None]:
        return parse_lead_customer_details(
            lead,
            client_email_field=self.settings.bitrix_field_client_email,
            fallback_email_field=self.settings.bitrix_field_customer_email,
        )


def _mail_fix_hint(exc: BitrixApiError) -> str:
    """Human-readable next step for the common Bitrix mail failures."""
    code = (exc.code or "").lower()
    detail = (exc.description or "").lower()

    if code in ("error_method_not_found", "method_not_found") or "method not found" in detail:
        return (
            "Bitrix portal does not expose mail.message.send — "
            "connect a mailbox in Bitrix Mail (Mail → connect mailbox), "
            "then set BITRIX_MAIL_FROM to that sender address; "
            "scope alone is not enough"
        )
    if code == "insufficient_scope" or exc.missing_scope == "mail":
        return "add_mail_scope_on_inbound_webhook_and_reconnect_token"
    if code in ("access_denied", "forbidden"):
        return "webhook_user_needs_mail_permission_or_mailbox_access"
    if "sender" in detail or "from" in detail:
        return "set_BITRIX_MAIL_FROM_to_an_address_returned_by_mail.mailbox.senders"
    if exc.missing_scope:
        return f"add_scope={exc.missing_scope}"
    return "check_BITRIX_MAIL_FROM_and_connected_Bitrix_mailbox"
