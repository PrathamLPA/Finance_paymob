"""Email integration — mock file logger and SendGrid stub."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings, get_settings
from app.integrations.base import InvoiceReference

logger = logging.getLogger(__name__)


class MockEmailClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.email_dir = Path(self.settings.storage_path) / "emails"
        self.email_dir.mkdir(parents=True, exist_ok=True)
        self.sent_emails: list[dict] = []

    def _write_email(self, subject: str, to_email: str, body: str, attachment: str | None = None) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filename = self.email_dir / f"{timestamp}_{to_email.replace('@', '_at_')}.txt"
        content = f"To: {to_email}\nSubject: {subject}\n\n{body}"
        if attachment:
            content += f"\n\nAttachment: {attachment}"
        filename.write_text(content, encoding="utf-8")
        self.sent_emails.append({"to": to_email, "subject": subject, "body": body, "attachment": attachment})
        logger.info("[MockEmail] Sent '%s' to %s", subject, to_email)

    def send_payment_request(
        self,
        *,
        to_email: str,
        customer_name: str | None,
        payment_url: str,
    ) -> None:
        name = customer_name or "Customer"
        body = (
            f"Dear {name},\n\n"
            f"Please complete your payment using the secure link below:\n\n"
            f"{payment_url}\n\n"
            f"You will be asked to review and accept our Terms and Conditions before proceeding.\n\n"
            f"Regards,\n{self.settings.sendgrid_from_name}"
        )
        self._write_email("Payment Request", to_email, body)

    def send_terms_acceptance(
        self,
        *,
        to_email: str,
        customer_name: str | None,
        pdf_path: str,
        terms_version: str,
    ) -> None:
        name = customer_name or "Customer"
        body = (
            f"Dear {name},\n\n"
            f"Thank you for accepting our Terms and Conditions (version {terms_version}).\n"
            f"A copy of the accepted terms is attached for your records.\n\n"
            f"Regards,\n{self.settings.sendgrid_from_name}"
        )
        self._write_email("Terms and Conditions Acceptance", to_email, body, attachment=pdf_path)

    def send_invoice(
        self,
        *,
        to_email: str,
        customer_name: str | None,
        invoice_reference: InvoiceReference,
        document_path: str | None,
    ) -> None:
        name = customer_name or "Customer"
        body = (
            f"Dear {name},\n\n"
            f"Please find your updated invoice ({invoice_reference.invoice_number}).\n\n"
            f"Total: {invoice_reference.currency} {invoice_reference.total_amount}\n"
            f"Paid: {invoice_reference.currency} {invoice_reference.amount_paid}\n"
            f"Remaining: {invoice_reference.currency} {invoice_reference.remaining_balance}\n\n"
            f"Regards,\n{self.settings.sendgrid_from_name}"
        )
        self._write_email("Updated Invoice", to_email, body, attachment=document_path)


class RealEmailClient(MockEmailClient):
    """SendGrid email client — falls back to mock when API key not configured."""

    def send_payment_request(
        self,
        *,
        to_email: str,
        customer_name: str | None,
        payment_url: str,
    ) -> None:
        if self.settings.use_mock_integrations or not self.settings.sendgrid_api_key:
            return super().send_payment_request(
                to_email=to_email, customer_name=customer_name, payment_url=payment_url
            )
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail

            name = customer_name or "Customer"
            message = Mail(
                from_email=(self.settings.sendgrid_from_email, self.settings.sendgrid_from_name),
                to_emails=to_email,
                subject="Payment Request",
                plain_text_content=(
                    f"Dear {name},\n\nPlease complete your payment: {payment_url}\n"
                ),
            )
            SendGridAPIClient(self.settings.sendgrid_api_key).send(message)
        except ImportError:
            super().send_payment_request(to_email=to_email, customer_name=customer_name, payment_url=payment_url)
