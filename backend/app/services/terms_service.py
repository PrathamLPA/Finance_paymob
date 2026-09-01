"""Terms and conditions acceptance flow."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fastapi import HTTPException
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.factory import get_bitrix_client, get_email_client
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import PaymentSession, SESSION_TERMS_ACCEPTED
from app.models.terms_acceptance import TermsAcceptance
from app.services.course_seats import (
    load_lead_courses,
    normalize_participants,
    participants_for_buyer,
    validate_participants,
)
from app.services.payment_session_service import PaymentSessionService

logger = logging.getLogger(__name__)


class TermsService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.session_service = PaymentSessionService(db, self.settings)
        self.email = get_email_client(self.settings)
        self.terms_path = Path(__file__).parent.parent / "content" / "terms_and_conditions.md"

    def load_terms_markdown(self) -> str:
        return self.terms_path.read_text(encoding="utf-8")

    def markdown_to_html(self, markdown: str) -> str:
        blocks: list[str] = []
        for block in markdown.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            if block.startswith("# "):
                blocks.append(f"<h2>{block[2:]}</h2>")
                continue
            if block.startswith("**") and block.endswith("**"):
                blocks.append(f'<p class="terms-version"><strong>{block[2:-2]}</strong></p>')
                continue

            lines = block.split("\n")
            if re.match(r"^\d+\.\s", lines[0]):
                blocks.append(f'<p class="terms-section-title"><strong>{lines[0]}</strong></p>')
                body_lines = lines[1:]
                if body_lines and all(line.startswith("- ") for line in body_lines):
                    items = "".join(f"<li>{line[2:]}</li>" for line in body_lines)
                    blocks.append(f"<ul>{items}</ul>")
                elif body_lines:
                    blocks.append(f"<p>{' '.join(body_lines)}</p>")
                continue

            if all(line.startswith("- ") for line in lines):
                items = "".join(f"<li>{line[2:]}</li>" for line in lines)
                blocks.append(f"<ul>{items}</ul>")
                continue

            blocks.append(f"<p>{block.replace(chr(10), ' ')}</p>")
        return "\n".join(blocks)

    def validate_registrant_details(
        self,
        *,
        course_for: str | None,
        registrant_name: str | None,
        registrant_email: str | None,
        registrant_phone: str | None,
    ) -> str | None:
        if course_for not in ("self", "someone_else"):
            return "Please select whether this course is for you or someone else."
        if not registrant_name or not registrant_name.strip():
            return "Please enter your name."
        if not registrant_email or not registrant_email.strip():
            return "Please enter your email address."
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", registrant_email.strip()):
            return "Please enter a valid email address."
        if not registrant_phone or not registrant_phone.strip():
            return "Please enter your phone number."
        return None

    def resolve_payment_amount(
        self,
        workflow: CustomerWorkflow,
        requested: Decimal | None,
        *,
        session: PaymentSession | None = None,
    ) -> Decimal:
        """Use the locked session amount when Bitrix set Installment 1 / full charge."""
        remaining = workflow.remaining_balance
        if remaining <= 0:
            raise HTTPException(status_code=400, detail="This balance is already settled.")

        if session is not None and session.amount_locked:
            locked = Decimal(session.charge_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if locked <= 0:
                raise HTTPException(status_code=400, detail="This payment link has no charge amount.")
            if locked > remaining:
                return remaining
            return locked

        minimum = workflow.minimum_due(self.settings.payment_required_percent)
        if requested is None:
            return remaining

        amount = Decimal(requested).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount < minimum:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"The minimum payment for this course is "
                    f"{minimum:.2f} {workflow.currency}."
                ),
            )
        if amount > remaining:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"The outstanding balance is only {remaining:.2f} {workflow.currency}."
                ),
            )
        return amount

    def get_terms_context(self, **form_values: str | None) -> dict:
        markdown = self.load_terms_markdown()
        return {
            "terms_version": self.settings.terms_version,
            "terms_html": self.markdown_to_html(markdown),
            "refund_policy_url": self.settings.refund_policy_url,
            "course_for": form_values.get("course_for"),
            "registrant_name": form_values.get("registrant_name") or "",
            "registrant_email": form_values.get("registrant_email") or "",
            "registrant_phone": form_values.get("registrant_phone") or "",
        }

    def generate_acceptance_pdf(
        self,
        session: PaymentSession,
        *,
        course_for: str,
        registrant_name: str,
        registrant_email: str,
        registrant_phone: str,
        participants: list[dict] | None = None,
    ) -> str:
        pdf_dir = Path(self.settings.storage_path) / "pdfs" / "terms"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"terms_acceptance_{session.id}_{session.token[:8]}.pdf"

        markdown = self.load_terms_markdown()
        course_label = "For me" if course_for == "self" else "For someone else"
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        c.drawString(72, 750, "Terms and Conditions — Acceptance Record")
        c.drawString(72, 730, f"Version: {self.settings.terms_version}")
        c.drawString(72, 710, f"Accepted at: {datetime.now(timezone.utc).isoformat()}")
        c.drawString(72, 690, f"Session token: {session.token[:16]}...")
        c.drawString(72, 670, f"Course registration: {course_label}")
        c.drawString(72, 650, f"Buyer name: {registrant_name[:70]}")
        c.drawString(72, 630, f"Buyer email: {registrant_email[:70]}")
        c.drawString(72, 610, f"Buyer phone: {registrant_phone[:70]}")

        y = 580
        if participants:
            c.drawString(72, y, "Course candidates:")
            y -= 16
            for index, person in enumerate(participants, start=1):
                if y < 72:
                    c.showPage()
                    y = 750
                label = (
                    f"{index}. {str(person.get('name') or '')[:40]} | "
                    f"{str(person.get('email') or '')[:40]} | "
                    f"{str(person.get('product_name') or '')[:40]}"
                )
                c.drawString(72, y, label[:95])
                y -= 14
            y -= 10

        for line in markdown.split("\n"):
            if y < 72:
                c.showPage()
                y = 750
            c.drawString(72, y, line[:90])
            y -= 14

        if y < 72:
            c.showPage()
            y = 750
        y -= 14
        c.drawString(72, y, f"Full refund policy: {self.settings.refund_policy_url}")

        c.save()
        return str(pdf_path)

    async def accept_terms(
        self,
        token: str,
        *,
        accepted: bool,
        ip_address: str | None = None,
        course_for: str,
        registrant_name: str,
        registrant_email: str,
        registrant_phone: str,
        payment_amount: Decimal | None = None,
        participants: list[dict] | None = None,
    ) -> str:
        if not accepted:
            raise HTTPException(status_code=400, detail="You must accept the Terms and Conditions to continue")

        validation_error = self.validate_registrant_details(
            course_for=course_for,
            registrant_name=registrant_name,
            registrant_email=registrant_email,
            registrant_phone=registrant_phone,
        )
        if validation_error:
            raise HTTPException(status_code=400, detail=validation_error)

        session = self.session_service.get_active_session_by_token(token)
        if not session:
            raise HTTPException(status_code=404, detail="Payment session not found or expired")

        bitrix = get_bitrix_client(self.settings)
        courses = await load_lead_courses(bitrix, session.workflow.bitrix_lead_id)
        if course_for == "self" and not participants:
            participants = participants_for_buyer(
                courses,
                name=registrant_name.strip(),
                email=registrant_email.strip(),
            )
        participants_error = validate_participants(courses, participants)
        if participants_error:
            raise HTTPException(status_code=400, detail=participants_error)
        cleaned_participants = normalize_participants(participants, courses)

        amount = self.resolve_payment_amount(
            session.workflow, payment_amount, session=session
        )

        from app.models.payment_session import CHANNEL_BANK_TRANSFER

        is_bank_transfer = (
            getattr(session, "channel", None) or ""
        ).strip().lower() == CHANNEL_BANK_TRANSFER

        if (
            not is_bank_transfer
            and session.status == SESSION_TERMS_ACCEPTED
            and session.paymob_checkout_url
        ):
            return await self.session_service.refresh_paymob_checkout(session, amount=amount)

        if session.status != SESSION_TERMS_ACCEPTED:
            pdf_path = self.generate_acceptance_pdf(
                session,
                course_for=course_for,
                registrant_name=registrant_name.strip(),
                registrant_email=registrant_email.strip(),
                registrant_phone=registrant_phone.strip(),
                participants=cleaned_participants,
            )

            acceptance = TermsAcceptance(
                payment_session_id=session.id,
                ip_address=ip_address,
                pdf_path=pdf_path,
                terms_version=self.settings.terms_version,
                course_for=course_for,
                registrant_name=registrant_name.strip(),
                registrant_email=registrant_email.strip(),
                registrant_phone=registrant_phone.strip(),
                participants_json=cleaned_participants or None,
            )
            self.db.add(acceptance)
            self.session_service.mark_terms_accepted(session)

            workflow = session.workflow
            workflow.customer_name = registrant_name.strip()
            workflow.customer_email = registrant_email.strip()
            workflow.customer_phone = registrant_phone.strip()
            self.db.commit()
            self.db.refresh(workflow)

            await self._sync_registrant_to_bitrix(workflow)

            if workflow.customer_email:
                self.email.send_terms_acceptance(
                    to_email=workflow.customer_email,
                    customer_name=workflow.customer_name,
                    pdf_path=pdf_path,
                    terms_version=self.settings.terms_version,
                )
        else:
            # Already accepted — keep charge amount in sync
            if amount != session.charge_amount:
                session.charge_amount = amount
                self.db.commit()

        if is_bank_transfer:
            if amount != session.charge_amount:
                session.charge_amount = amount
                self.db.commit()
            from app.services.bank_transfer_service import BankTransferService

            BankTransferService(self.db, self.settings).enqueue_for_session(session)
            return self.session_service.build_receipt_upload_url(session.token)

        if amount != session.charge_amount or not session.paymob_checkout_url:
            return await self.session_service.refresh_paymob_checkout(session, amount=amount)

        return session.paymob_checkout_url

    async def _sync_registrant_to_bitrix(self, workflow: CustomerWorkflow) -> None:
        bitrix = get_bitrix_client(self.settings)
        deal_ids = [workflow.sales_deal_id, workflow.finance_deal_id, workflow.b2c_deal_id]
        for deal_id in deal_ids:
            if not deal_id:
                continue
            try:
                await bitrix.sync_deal_customer_details(
                    deal_id,
                    name=workflow.customer_name,
                    email=workflow.customer_email,
                    phone=workflow.customer_phone,
                )
            except Exception:
                logger.exception("Failed to sync registrant to Bitrix deal %s", deal_id)
