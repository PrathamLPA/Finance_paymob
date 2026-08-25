"""Email integration — mock file logger and SendGrid."""

from __future__ import annotations

import base64
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
    ) -> None:
        name = customer_name or "Customer"
        amount_line = f"Amount due: {currency} {amount}\n" if amount else ""
        body = (
            f"Dear {name},\n\n"
            f"This is a reminder that installment {installment_number} is due on {due_date}.\n"
            f"{amount_line}\n"
            f"Please complete your payment using the secure link below:\n\n"
            f"{payment_url}\n\n"
            f"Regards,\n{self.settings.sendgrid_from_name}"
        )
        self._write_email(
            f"Installment {installment_number} due {due_date}",
            to_email,
            body,
        )

    def send_price_approval(
        self,
        *,
        to_email: str,
        manager_name: str | None,
        subject: str,
        body: str,
    ) -> bool:
        # Body already includes greeting / approval URL from PriceApprovalService.
        self._write_email(subject, to_email, body)
        return True

    def send_agent_payment_notice(
        self,
        *,
        to_email: str,
        agent_name: str | None,
        subject: str,
        body: str,
    ) -> bool:
        self._write_email(subject, to_email, body)
        return True

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
    """SendGrid email client."""

    def _sendgrid_ready(self) -> bool:
        return not self.settings.use_mock_integrations and bool(self.settings.sendgrid_api_key)

    def _build_attachment(self, path: str | None):
        if not path or not Path(path).exists():
            return None
        try:
            from sendgrid.helpers.mail import Attachment, Disposition, FileContent, FileName, FileType

            raw = Path(path).read_bytes()
            encoded = base64.b64encode(raw).decode()
            return Attachment(
                FileContent(encoded),
                FileName(Path(path).name),
                FileType("application/pdf"),
                Disposition("attachment"),
            )
        except Exception:
            logger.exception("Failed to build SendGrid attachment from %s", path)
            return None

    def _send_mail(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        attachment_path: str | None = None,
    ) -> bool:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail

            message = Mail(
                from_email=(self.settings.sendgrid_from_email, self.settings.sendgrid_from_name),
                to_emails=to_email,
                subject=subject,
                plain_text_content=body,
            )
            attachment = self._build_attachment(attachment_path)
            if attachment:
                message.attachment = attachment
            response = SendGridAPIClient(self.settings.sendgrid_api_key).send(message)
            status = int(getattr(response, "status_code", 0) or 0)
            headers = getattr(response, "headers", {}) or {}
            message_id = headers.get("X-Message-Id") or headers.get("x-message-id") or "-"
            if 200 <= status < 300:
                logger.info(
                    "OK SendGrid accepted | to=%s from=%s subject=%s status=%s message_id=%s",
                    to_email,
                    self.settings.sendgrid_from_email,
                    subject,
                    status,
                    message_id,
                )
                return True
            logger.error(
                "FAIL SendGrid response | to=%s from=%s subject=%s status=%s "
                "message_id=%s action=check_SendGrid_activity_and_sender_verification",
                to_email,
                self.settings.sendgrid_from_email,
                subject,
                status,
                message_id,
            )
            return False
        except ImportError:
            logger.error(
                "FAIL SendGrid | reason=package_not_installed action=install_sendgrid"
            )
            return False
        except Exception as exc:
            response_body = getattr(exc, "body", None)
            logger.exception(
                "FAIL SendGrid exception | to=%s from=%s subject=%s error=%s "
                "response=%s action=check_API_key_sender_verification_and_SendGrid_activity",
                to_email,
                self.settings.sendgrid_from_email,
                subject,
                type(exc).__name__,
                response_body or "-",
            )
            return False

    def send_payment_request(
        self,
        *,
        to_email: str,
        customer_name: str | None,
        payment_url: str,
    ) -> None:
        if not self._sendgrid_ready():
            return super().send_payment_request(
                to_email=to_email, customer_name=customer_name, payment_url=payment_url
            )
        name = customer_name or "Customer"
        body = (
            f"Dear {name},\n\n"
            f"Please complete your payment using the secure link below:\n\n"
            f"{payment_url}\n\n"
            f"You will be asked to review and accept our Terms and Conditions before proceeding.\n\n"
            f"Regards,\n{self.settings.sendgrid_from_name}"
        )
        if not self._send_mail(to_email=to_email, subject="Payment Request", body=body):
            super().send_payment_request(
                to_email=to_email, customer_name=customer_name, payment_url=payment_url
            )

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
    ) -> None:
        if not self._sendgrid_ready():
            return super().send_installment_reminder(
                to_email=to_email,
                customer_name=customer_name,
                payment_url=payment_url,
                installment_number=installment_number,
                due_date=due_date,
                amount=amount,
                currency=currency,
            )
        name = customer_name or "Customer"
        amount_line = f"Amount due: {currency} {amount}\n" if amount else ""
        body = (
            f"Dear {name},\n\n"
            f"This is a reminder that installment {installment_number} is due on {due_date}.\n"
            f"{amount_line}\n"
            f"Please complete your payment using the secure link below:\n\n"
            f"{payment_url}\n\n"
            f"Regards,\n{self.settings.sendgrid_from_name}"
        )
        subject = f"Installment {installment_number} due {due_date}"
        if not self._send_mail(to_email=to_email, subject=subject, body=body):
            super().send_installment_reminder(
                to_email=to_email,
                customer_name=customer_name,
                payment_url=payment_url,
                installment_number=installment_number,
                due_date=due_date,
                amount=amount,
                currency=currency,
            )

    def send_price_approval(
        self,
        *,
        to_email: str,
        manager_name: str | None,
        subject: str,
        body: str,
    ) -> bool:
        if not self._sendgrid_ready():
            logger.error(
                "SKIP SendGrid approval | to=%s reason=not_configured "
                "mock_integrations=%s has_api_key=%s action=set_SENDGRID_API_KEY",
                to_email,
                self.settings.use_mock_integrations,
                bool(self.settings.sendgrid_api_key),
            )
            return False
        return self._send_mail(to_email=to_email, subject=subject, body=body)

    def send_agent_payment_notice(
        self,
        *,
        to_email: str,
        agent_name: str | None,
        subject: str,
        body: str,
    ) -> bool:
        if not self._sendgrid_ready():
            logger.error(
                "SKIP SendGrid agent notice | to=%s reason=not_configured action=set_SENDGRID_API_KEY",
                to_email,
            )
            return False
        return self._send_mail(to_email=to_email, subject=subject, body=body)

    def send_terms_acceptance(
        self,
        *,
        to_email: str,
        customer_name: str | None,
        pdf_path: str,
        terms_version: str,
    ) -> None:
        if not self._sendgrid_ready():
            return super().send_terms_acceptance(
                to_email=to_email,
                customer_name=customer_name,
                pdf_path=pdf_path,
                terms_version=terms_version,
            )
        name = customer_name or "Customer"
        body = (
            f"Dear {name},\n\n"
            f"Thank you for accepting our Terms and Conditions (version {terms_version}).\n"
            f"A copy of the accepted terms is attached for your records.\n\n"
            f"Regards,\n{self.settings.sendgrid_from_name}"
        )
        if not self._send_mail(
            to_email=to_email,
            subject="Terms and Conditions Acceptance",
            body=body,
            attachment_path=pdf_path,
        ):
            super().send_terms_acceptance(
                to_email=to_email,
                customer_name=customer_name,
                pdf_path=pdf_path,
                terms_version=terms_version,
            )

    def send_invoice(
        self,
        *,
        to_email: str,
        customer_name: str | None,
        invoice_reference: InvoiceReference,
        document_path: str | None,
    ) -> None:
        if not self._sendgrid_ready():
            return super().send_invoice(
                to_email=to_email,
                customer_name=customer_name,
                invoice_reference=invoice_reference,
                document_path=document_path,
            )
        name = customer_name or "Customer"
        body = (
            f"Dear {name},\n\n"
            f"Please find your updated invoice ({invoice_reference.invoice_number}).\n\n"
            f"Total: {invoice_reference.currency} {invoice_reference.total_amount}\n"
            f"Paid: {invoice_reference.currency} {invoice_reference.amount_paid}\n"
            f"Remaining: {invoice_reference.currency} {invoice_reference.remaining_balance}\n\n"
            f"Regards,\n{self.settings.sendgrid_from_name}"
        )
        if not self._send_mail(
            to_email=to_email,
            subject="Updated Invoice",
            body=body,
            attachment_path=document_path,
        ):
            super().send_invoice(
                to_email=to_email,
                customer_name=customer_name,
                invoice_reference=invoice_reference,
                document_path=document_path,
            )
