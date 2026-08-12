"""Bitrix24 integration — real stub and mock implementation."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.integrations.base import InvoiceReference, PaymentSummary

logger = logging.getLogger(__name__)


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
        self._next_estimate_id = self.MOCK_ESTIMATE_BASE

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
    ) -> int | None:
        comments = self._mock_comments.setdefault((entity_type.upper(), entity_id), [])
        comment_id = len(comments) + 1
        comments.append({"id": comment_id, "COMMENT": comment})
        logger.info(
            "[MockBitrix] Timeline comment on %s %s: %s",
            entity_type,
            entity_id,
            comment[:120],
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

    def extract_lead_amount(self, lead: dict[str, Any]) -> Decimal:
        return extract_amount(lead, self.settings.bitrix_field_lead_amount)

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

    @staticmethod
    def _scalar(result: dict[str, Any]) -> Any:
        """_call wraps non-dict REST results as {"result": value}; unwrap them."""
        if isinstance(result, dict) and set(result) == {"result"}:
            return result["result"]
        return result

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
    ) -> int | None:
        result = await self._call(
            "crm.timeline.comment.add",
            {
                "fields": {
                    "ENTITY_TYPE": entity_type.upper(),
                    "ENTITY_ID": entity_id,
                    "COMMENT": comment,
                }
            },
        )
        raw = self._scalar(result)
        try:
            comment_id = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            comment_id = None
        logger.info(
            "Added Bitrix timeline comment id=%s on %s %s",
            comment_id if comment_id is not None else "-",
            entity_type,
            entity_id,
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

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        result = await self._call("user.get", {"ID": user_id})
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
            except Exception:
                logger.exception("mail.mailbox.senders failed")
        if not sender:
            logger.error(
                "Bitrix mail send skipped reason=no_from_address "
                "action=set_BITRIX_MAIL_FROM"
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
        except Exception:
            logger.exception("mail.message.send failed to=%s", to_email)
            return False

        success = True
        if isinstance(result, dict):
            if "success" in result:
                success = bool(result.get("success"))
            nested = result.get("result")
            if isinstance(nested, dict) and "success" in nested:
                success = bool(nested.get("success"))
        if success:
            logger.info("Bitrix mail sent '%s' to %s from %s", subject, to_email, sender)
        else:
            logger.error("Bitrix mail rejected for %s: %s", to_email, result)
        return success

    def extract_lead_amount(self, lead: dict[str, Any]) -> Decimal:
        return extract_amount(lead, self.settings.bitrix_field_lead_amount)

    def extract_customer_details(self, lead: dict[str, Any]) -> tuple[str | None, str | None]:
        emails = lead.get("EMAIL") or []
        email = emails[0].get("VALUE") if emails else None
        name_parts = [lead.get("NAME"), lead.get("LAST_NAME")]
        name = " ".join(p for p in name_parts if p).strip() or None
        return (email, name)
