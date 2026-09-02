"""Shared integration types and protocols."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol


@dataclass
class PaymobSession:
    session_id: str
    checkout_url: str
    order_id: str | None = None


@dataclass
class PaymentWebhookData:
    transaction_id: str
    amount: Decimal
    currency: str
    merchant_reference: str
    order_id: str | None
    raw_payload: str | None
    # Paymob transaction callback fields (developers.paymob.com)
    amount_cents: int | None = None
    paymob_created_at: str | None = None
    error_occured: bool = False
    has_parent_transaction: bool = False
    paymob_integration_id: int | None = None
    is_3d_secure: bool = False
    is_auth: bool = False
    is_capture: bool = False
    is_refunded: bool = False
    is_standalone_payment: bool = True
    is_voided: bool = False
    paymob_order_id: str | None = None
    owner: int | None = None
    pending: bool = False
    source_pan: str | None = None
    source_sub_type: str | None = None
    source_type: str | None = None
    success: bool = True


@dataclass
class InvoiceReference:
    invoice_id: str
    invoice_number: str
    pdf_url: str | None
    pdf_path: str | None
    amount_paid: Decimal
    total_amount: Decimal
    remaining_balance: Decimal
    currency: str


@dataclass
class InvoiceDocument:
    invoice_id: str
    pdf_url: str | None
    pdf_path: str | None
    pdf_bytes: bytes | None


@dataclass
class PaymentSummary:
    total_amount: Decimal
    amount_paid: Decimal
    remaining_balance: Decimal
    currency: str
    latest_transaction_id: str | None
    payment_percentage: Decimal | None = None
    payment_status: str | None = None


class BitrixIntegration(Protocol):
    async def get_lead(self, lead_id: int) -> dict[str, Any]: ...

    async def get_deal(self, deal_id: int) -> dict[str, Any]: ...

    async def convert_lead_to_sales_deal(self, lead_id: int, context: dict[str, Any]) -> int: ...

    async def create_finance_deal(self, lead_id: int, context: dict[str, Any]) -> int: ...

    async def create_b2c_deal(self, lead_id: int, context: dict[str, Any]) -> int: ...

    async def attach_invoice_reference(self, deal_id: int, invoice: InvoiceReference) -> None: ...

    async def update_deal_payment_summary(self, deal_id: int, summary: PaymentSummary) -> None: ...

    async def set_deal_payment_link(self, deal_id: int, payment_url: str) -> None: ...

    async def add_timeline_comment(
        self,
        *,
        entity_type: str,
        entity_id: int,
        comment: str,
        files: list[tuple[str, bytes]] | None = None,
    ) -> int | None: ...

    async def set_deal_stage(self, deal_id: int, stage_id: str) -> None: ...

    async def sync_deal_customer_details(
        self,
        deal_id: int,
        *,
        name: str | None,
        email: str | None,
        phone: str | None,
    ) -> None: ...

    async def list_product_rows(self, *, owner_type: str, owner_id: int) -> list[dict[str, Any]]: ...

    async def get_catalog_min_price(self, product_id: int) -> Decimal | None: ...

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
    ) -> int: ...

    async def update_estimate(
        self,
        estimate_id: int,
        *,
        currency: str,
        opportunity: Decimal,
        tax_value: Decimal,
        product_rows: list[dict[str, Any]],
        comments: str | None = None,
    ) -> None: ...

    async def update_lead_fields(self, lead_id: int, fields: dict[str, Any]) -> None: ...

    async def set_lead_product_rows(
        self, lead_id: int, product_rows: list[dict[str, Any]]
    ) -> None: ...

    async def get_user(self, user_id: int) -> dict[str, Any] | None: ...

    async def resolve_manager_for_user(self, user_id: int) -> dict[str, Any] | None: ...

    async def send_mail(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        from_email: str | None = None,
    ) -> bool: ...

    async def notify_user(self, *, user_id: int, message: str) -> bool: ...

    def extract_lead_amount(self, lead: dict[str, Any]) -> Decimal: ...

    def extract_customer_details(self, lead: dict[str, Any]) -> tuple[str | None, str | None]: ...


class PaymobIntegration(Protocol):
    async def create_payment_session(
        self,
        *,
        amount: Decimal,
        currency: str,
        merchant_reference: str,
        customer_email: str | None,
        customer_name: str | None,
        payment_method_ids: list[int] | None = None,
    ) -> PaymobSession: ...

    def verify_webhook(self, payload: dict[str, Any], signature: str | None) -> bool: ...

    def parse_successful_payment(self, payload: dict[str, Any]) -> PaymentWebhookData | None: ...

    def parse_payment_callback(self, payload: dict[str, Any]) -> PaymentWebhookData | None: ...


class ZohoBooksIntegration(Protocol):
    async def create_invoice(
        self,
        *,
        workflow_id: int,
        customer_name: str | None,
        customer_email: str | None,
        total_amount: Decimal,
        amount_paid: Decimal,
        currency: str,
        transaction_id: str,
    ) -> InvoiceReference: ...

    async def apply_payment_to_invoice(
        self,
        *,
        invoice_id: str,
        amount: Decimal,
        currency: str,
        transaction_id: str,
        total_amount: Decimal,
        amount_paid: Decimal,
    ) -> InvoiceReference: ...

    async def get_invoice_document(self, invoice_id: str) -> InvoiceDocument: ...


class EmailIntegration(Protocol):
    def send_payment_request(
        self,
        *,
        to_email: str,
        customer_name: str | None,
        payment_url: str,
    ) -> None: ...

    def send_installment_reminder(
        self,
        *,
        to_email: str,
        customer_name: str | None,
        payment_url: str,
        installment_number: int,
        due_date: str,
        amount: str | None,
        currency: str,
    ) -> None: ...

    def send_price_approval(
        self,
        *,
        to_email: str,
        manager_name: str | None,
        subject: str,
        body: str,
    ) -> bool: ...

    def send_agent_payment_notice(
        self,
        *,
        to_email: str,
        agent_name: str | None,
        subject: str,
        body: str,
    ) -> bool: ...

    def send_terms_acceptance(
        self,
        *,
        to_email: str,
        customer_name: str | None,
        pdf_path: str,
        terms_version: str,
    ) -> None: ...

    def send_invoice(
        self,
        *,
        to_email: str,
        customer_name: str | None,
        invoice_reference: InvoiceReference,
        document_path: str | None,
    ) -> None: ...
