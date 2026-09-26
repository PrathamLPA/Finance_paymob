"""Terms and conditions acceptance flow."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
    # Tabby HPP expires ~20 min; reuse only while still likely valid.
    BNPL_CHECKOUT_REUSE_MINUTES = 15

    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.session_service = PaymentSessionService(db, self.settings)
        self.email = get_email_client(self.settings)
        self.terms_path = Path(__file__).parent.parent / "content" / "terms_and_conditions.md"

    @staticmethod
    def _bnpl_checkout_stale(session: PaymentSession) -> bool:
        """True when terms were accepted long enough ago that Tabby/Tamara HPP may have expired."""
        from datetime import datetime, timedelta, timezone

        acceptance = getattr(session, "terms_acceptance", None)
        accepted_at = getattr(acceptance, "accepted_at", None) if acceptance else None
        if accepted_at is None:
            return True
        if accepted_at.tzinfo is None:
            accepted_at = accepted_at.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - accepted_at.astimezone(timezone.utc)
        return age > timedelta(minutes=TermsService.BNPL_CHECKOUT_REUSE_MINUTES)

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

        if session is not None and session.amount_locked:
            locked = Decimal(session.charge_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if locked <= 0:
                raise HTTPException(status_code=400, detail="This payment link has no charge amount.")
            # Locked installment charges are authoritative for this payment session.
            # Cap at remaining when a positive balance exists; otherwise honor the lock
            # (workflow totals can be stale vs the installment plan on the session).
            if remaining > 0 and locked > remaining:
                return remaining
            return locked

        if remaining <= 0:
            raise HTTPException(status_code=400, detail="This balance is already settled.")

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

    def _terms_plain_lines(self) -> list[str]:
        """Plain-text lines of the published T&C for the emailed PDF."""
        try:
            raw = self.load_terms_markdown()
        except OSError:
            logger.warning("Could not load terms markdown for PDF; using fallback notice")
            return [
                "The full Terms and Conditions were accepted online.",
                f"See: {self.settings.refund_policy_url}",
            ]

        lines: list[str] = []
        for line in raw.splitlines():
            text = line.rstrip()
            if not text.strip():
                lines.append("")
                continue
            if text.startswith("# "):
                lines.append(text[2:].strip())
                continue
            if text.startswith("- "):
                lines.append(f"• {text[2:].strip()}")
                continue
            lines.append(text)
        return lines

    @staticmethod
    def _pdf_draw_wrapped(
        c: canvas.Canvas,
        text: str,
        *,
        x: float,
        y: float,
        max_width: float,
        font: str = "Helvetica",
        size: int = 10,
        leading: float = 14,
    ) -> float:
        """Draw wrapped text; return the y position after the last line."""
        c.setFont(font, size)
        words = text.split()
        if not words:
            return y - leading
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if c.stringWidth(trial, font, size) <= max_width:
                current = trial
            else:
                if y < 72:
                    c.showPage()
                    c.setFont(font, size)
                    y = 750
                c.drawString(x, y, current)
                y -= leading
                current = word
        if y < 72:
            c.showPage()
            c.setFont(font, size)
            y = 750
        c.drawString(x, y, current)
        return y - leading

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
        """Build a PDF with acceptance details + the full Terms and Conditions body."""
        pdf_dir = Path(self.settings.storage_path) / "pdfs" / "terms"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"terms_acceptance_{session.id}_{session.token[:8]}.pdf"

        course_label = "For me" if course_for == "self" else "For someone else"
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, 750, "Terms and Conditions - Acceptance Record")
        c.setFont("Helvetica", 10)
        y = 728
        for line in (
            f"Version: {self.settings.terms_version}",
            f"Accepted at: {datetime.now(timezone.utc).isoformat()}",
            f"Session token: {session.token[:16]}...",
            f"Course registration: {course_label}",
            f"Buyer name: {registrant_name[:70]}",
            f"Buyer email: {registrant_email[:70]}",
            f"Buyer phone: {registrant_phone[:70]}",
        ):
            c.drawString(72, y, line)
            y -= 16

        if participants:
            y -= 6
            c.setFont("Helvetica-Bold", 10)
            c.drawString(72, y, "Course candidates:")
            y -= 16
            c.setFont("Helvetica", 9)
            for index, person in enumerate(participants, start=1):
                if y < 72:
                    c.showPage()
                    c.setFont("Helvetica", 9)
                    y = 750
                label = (
                    f"{index}. {str(person.get('name') or '')[:40]} | "
                    f"{str(person.get('email') or '')[:40]} | "
                    f"{str(person.get('product_name') or '')[:40]}"
                )
                c.drawString(72, y, label[:95])
                y -= 14

        y -= 8
        if y < 100:
            c.showPage()
            y = 750
        c.setFont("Helvetica", 10)
        c.drawString(72, y, "The customer accepted the Terms and Conditions below online.")
        y -= 16
        c.drawString(72, y, f"Refund policy URL: {self.settings.refund_policy_url}")
        y -= 24

        # Full policy body (runs in a background task after Accept).
        c.setFont("Helvetica-Bold", 12)
        if y < 100:
            c.showPage()
            y = 750
        c.drawString(72, y, "Terms and Conditions")
        y -= 20

        for plain in self._terms_plain_lines():
            if not plain.strip():
                y -= 8
                continue
            is_heading = plain[:1].isdigit() or plain in (
                "Payment Terms and Conditions",
            )
            font = "Helvetica-Bold" if is_heading else "Helvetica"
            size = 11 if is_heading else 10
            if y < 72:
                c.showPage()
                y = 750
            y = self._pdf_draw_wrapped(
                c,
                plain,
                x=72,
                y=y,
                max_width=468,
                font=font,
                size=size,
                leading=14 if not is_heading else 16,
            )
            if is_heading:
                y -= 2

        c.save()
        return str(pdf_path)

    @staticmethod
    async def run_acceptance_side_effects(
        *,
        session_id: int,
        workflow_id: int,
        course_for: str,
        registrant_name: str,
        registrant_email: str,
        registrant_phone: str,
        participants: list[dict[str, Any]] | None,
        terms_to_email: str | None = None,
    ) -> None:
        """PDF + Bitrix sync + email after the customer already got their next URL."""
        from app.db.session import SessionLocal
        from app.services.email_validation import is_valid_email

        db = SessionLocal()
        try:
            service = TermsService(db)
            session = db.get(PaymentSession, session_id)
            if not session:
                logger.warning(
                    "Deferred terms side effects skipped: missing session %s", session_id
                )
                return

            pdf_path = service.generate_acceptance_pdf(
                session,
                course_for=course_for,
                registrant_name=registrant_name,
                registrant_email=registrant_email,
                registrant_phone=registrant_phone,
                participants=participants,
            )
            acceptance = (
                db.query(TermsAcceptance)
                .filter(TermsAcceptance.payment_session_id == session_id)
                .order_by(TermsAcceptance.id.desc())
                .first()
            )
            if acceptance and not acceptance.pdf_path:
                acceptance.pdf_path = pdf_path
                db.commit()

            workflow = db.get(CustomerWorkflow, workflow_id)
            if not workflow:
                return

            await service._sync_registrant_to_bitrix(
                workflow,
                course_for=course_for,
                registrant_name=registrant_name,
                registrant_email=registrant_email,
                registrant_phone=registrant_phone,
                participants=participants,
            )
            # Prefer the email filled on the terms form; fall back to payment-link / workflow.
            to_email = (
                (terms_to_email or "").strip()
                or (registrant_email or "").strip()
                or (workflow.customer_email or "").strip()
            )
            mail_name = (registrant_name or "").strip() or workflow.customer_name
            if to_email and is_valid_email(to_email):
                await asyncio.to_thread(
                    service.email.send_terms_acceptance,
                    to_email=to_email,
                    customer_name=mail_name,
                    pdf_path=pdf_path,
                    terms_version=service.settings.terms_version,
                )
                logger.info(
                    "Terms acceptance emailed | session_id=%s to=%s registrant=%s",
                    session_id,
                    to_email,
                    registrant_email,
                )
            elif to_email:
                logger.warning(
                    "Terms acceptance email skipped — invalid address | session_id=%s to=%s",
                    session_id,
                    to_email,
                )
        except Exception:
            logger.exception(
                "Deferred terms acceptance side effects failed | session_id=%s",
                session_id,
            )
        finally:
            db.close()

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
        payment_mode: str | None = None,
        participants: list[dict] | None = None,
        background_tasks: BackgroundTasks | None = None,
    ) -> str:
        if not accepted:
            raise HTTPException(status_code=400, detail="You must accept the Terms and Conditions to continue")

        session = self.session_service.get_active_session_by_token(token)
        if not session:
            raise HTTPException(status_code=404, detail="Payment session not found or expired")

        # Installment 2+ reuses the verified identity and candidate allocation
        # captured with the first payment. The repeated page only asks the payer
        # to confirm the amount, payment method, and current terms.
        is_subsequent_payment = bool(
            session.workflow.amount_paid > 0
            or (
                getattr(session, "installment_number", None)
                and session.installment_number > 1
            )
        )
        if is_subsequent_payment:
            prior_acceptance = self.db.scalar(
                select(TermsAcceptance)
                .join(PaymentSession)
                .where(
                    PaymentSession.workflow_id == session.workflow_id,
                    PaymentSession.id != session.id,
                )
                .order_by(TermsAcceptance.accepted_at.desc())
            )
            if prior_acceptance:
                course_for = prior_acceptance.course_for or course_for or "self"
                registrant_name = (
                    prior_acceptance.registrant_name
                    or session.workflow.customer_name
                    or registrant_name
                )
                registrant_email = (
                    prior_acceptance.registrant_email
                    or session.workflow.customer_email
                    or registrant_email
                )
                registrant_phone = (
                    prior_acceptance.registrant_phone
                    or session.workflow.customer_phone
                    or registrant_phone
                )
                participants = prior_acceptance.participants_json or participants

        validation_error = self.validate_registrant_details(
            course_for=course_for,
            registrant_name=registrant_name,
            registrant_email=registrant_email,
            registrant_phone=registrant_phone,
        )
        if validation_error:
            raise HTTPException(status_code=400, detail=validation_error)

        from app.services.payment_mode import (
            resolve_session_channel_from_bitrix,
        )

        bitrix = get_bitrix_client(self.settings)
        courses = await load_lead_courses(bitrix, session.workflow.bitrix_lead_id)
        if course_for == "self":
            # Buyer is the only student — assign them to every course on the order.
            participants = participants_for_buyer(
                courses,
                name=registrant_name.strip(),
                email=registrant_email.strip(),
            )
        else:
            participants_error = validate_participants(courses, participants)
            if participants_error:
                raise HTTPException(status_code=400, detail=participants_error)
        cleaned_participants = normalize_participants(participants, courses)

        amount = self.resolve_payment_amount(
            session.workflow, payment_amount, session=session
        )

        from app.models.payment_session import (
            CHANNEL_BANK_TRANSFER,
            CHANNEL_CASH,
            CHANNEL_ONLINE,
        )

        # Payment channel comes from Bitrix Payment Mode for this installment —
        # customers no longer choose Card / Tabby / Cash on the terms page.
        number = getattr(session, "installment_number", None) or 1
        lead: dict = {}
        workflow = session.workflow
        if workflow.bitrix_lead_id:
            try:
                lead = await bitrix.get_lead(workflow.bitrix_lead_id) or {}
                if lead:
                    workflow.bitrix_lead_payload = lead
                    self.db.commit()
            except Exception:
                logger.exception(
                    "Could not refresh Bitrix lead %s before terms accept channel",
                    workflow.bitrix_lead_id,
                )
                lead = workflow.bitrix_lead_payload or {}
        else:
            lead = workflow.bitrix_lead_payload or {}

        # Later installments: only honor that installment's own mode (no cross-fallback).
        allow_fallback = number <= 1
        chosen_channel = await resolve_session_channel_from_bitrix(
            lead if isinstance(lead, dict) else {},
            installment_number=number,
            settings=self.settings,
            bitrix=bitrix,
            allow_cross_installment_fallback=allow_fallback,
        )
        session.customer_payment_mode = None
        session.channel = chosen_channel or getattr(session, "channel", None) or CHANNEL_ONLINE
        self.db.commit()
        self.db.refresh(session)

        is_bank_transfer = session.channel == CHANNEL_BANK_TRANSFER
        is_cash = session.channel == CHANNEL_CASH

        # Snapshot payment-link inbox before overwriting with form details.
        payment_link_email = (workflow.customer_email or "").strip()
        form_email = registrant_email.strip()

        # Always use the form details for Paymob / Bitrix, even on re-submit.
        workflow.customer_name = registrant_name.strip()
        workflow.customer_email = form_email
        workflow.customer_phone = registrant_phone.strip()
        self.db.commit()
        self.db.refresh(workflow)

        first_accept_this_request = False
        if session.status != SESSION_TERMS_ACCEPTED:
            # Persist acceptance immediately; PDF / Bitrix / email run after response.
            acceptance = TermsAcceptance(
                payment_session_id=session.id,
                ip_address=ip_address,
                pdf_path=None,
                terms_version=self.settings.terms_version,
                course_for=course_for,
                registrant_name=registrant_name.strip(),
                registrant_email=registrant_email.strip(),
                registrant_phone=registrant_phone.strip(),
                participants_json=cleaned_participants or None,
            )
            self.db.add(acceptance)
            self.session_service.mark_terms_accepted(session)
            try:
                self.db.commit()
                first_accept_this_request = True
            except IntegrityError:
                # Concurrent double-submit: another request already accepted.
                self.db.rollback()
                session = self.session_service.get_active_session_by_token(token)
                if not session:
                    raise HTTPException(
                        status_code=404, detail="Payment session not found or expired"
                    )
                self.db.refresh(session)
                workflow = session.workflow
                logger.info(
                    "Terms accept race recovered | session_id=%s status=%s",
                    session.id,
                    session.status,
                )
            if first_accept_this_request:
                side_effect_kwargs = {
                    "session_id": session.id,
                    "workflow_id": workflow.id,
                    "course_for": course_for,
                    "registrant_name": registrant_name.strip(),
                    "registrant_email": registrant_email.strip(),
                    "registrant_phone": registrant_phone.strip(),
                    "participants": cleaned_participants,
                    # Send the T&C PDF to the email entered on the form.
                    "terms_to_email": form_email or payment_link_email,
                }
                if background_tasks is not None:
                    background_tasks.add_task(
                        TermsService.run_acceptance_side_effects,
                        **side_effect_kwargs,
                    )
                else:
                    await TermsService.run_acceptance_side_effects(**side_effect_kwargs)
        else:
            # Already accepted: keep charge amount in sync
            if amount != session.charge_amount:
                session.charge_amount = amount
                self.db.commit()

        # Release the DB connection before long Paymob / enqueue work.
        self.db.commit()

        if is_cash:
            if amount != session.charge_amount:
                session.charge_amount = amount
                self.db.commit()
            from app.services.cash_collection_service import CashCollectionService

            cash = CashCollectionService(self.db, self.settings)
            collection = cash.enqueue_from_workflow(
                workflow,
                due_amount=amount,
                installment_number=getattr(session, "installment_number", None) or 1,
            )
            cash.link_payment_session(collection, session.id)
            cash.mark_details_ready(
                workflow_id=workflow.id,
                installment_number=getattr(session, "installment_number", None),
                payment_session_id=session.id,
                customer_name=registrant_name.strip(),
                customer_email=registrant_email.strip(),
                customer_phone=registrant_phone.strip(),
            )
            return self.session_service.build_cash_thank_you_url(
                session, name=registrant_name.strip()
            )

        if is_bank_transfer:
            if amount != session.charge_amount:
                session.charge_amount = amount
                self.db.commit()
            from app.services.bank_transfer_service import BankTransferService

            BankTransferService(self.db, self.settings).enqueue_for_session(session)
            return self.session_service.build_receipt_upload_url(session.token)

        from app.services.payment_mode import (
            resolve_is_tabby_payment_mode,
            resolve_is_tamara_payment_mode,
        )

        is_tabby = await resolve_is_tabby_payment_mode(
            lead if isinstance(lead, dict) else {},
            installment_number=number,
            settings=self.settings,
            bitrix=bitrix,
            allow_cross_installment_fallback=allow_fallback,
        )
        is_tamara = False
        if not is_tabby:
            is_tamara = await resolve_is_tamara_payment_mode(
                lead if isinstance(lead, dict) else {},
                installment_number=number,
                settings=self.settings,
                bitrix=bitrix,
                allow_cross_installment_fallback=allow_fallback,
            )

        try:
            # First accept always refreshes so gateway gets registrant details.
            # Re-submit reuses checkout unless amount/URL require a new session
            # (avoids rotating merchant_reference on double-click).
            needs_refresh = (
                first_accept_this_request
                or amount != session.charge_amount
                or not session.paymob_checkout_url
            )
            # Tabby/Tamara HPP expires ~20 minutes. Reuse only a fresh checkout so we
            # do not orphan a payment the customer already started on an older HPP.
            if is_tabby:
                if (
                    needs_refresh
                    or not getattr(session, "tabby_payment_id", None)
                    or self._bnpl_checkout_stale(session)
                ):
                    return await self.session_service.refresh_tabby_checkout(
                        session, amount=amount
                    )
                return session.paymob_checkout_url
            if is_tamara:
                if (
                    needs_refresh
                    or not getattr(session, "tamara_order_id", None)
                    or self._bnpl_checkout_stale(session)
                ):
                    return await self.session_service.refresh_tamara_checkout(
                        session, amount=amount
                    )
                return session.paymob_checkout_url
            if needs_refresh:
                return await self.session_service.refresh_paymob_checkout(
                    session, amount=amount
                )
            return session.paymob_checkout_url
        except ValueError as exc:
            message = str(exc)
            if is_tabby:
                if "not eligible" in message.lower() or "rejected" in message.lower():
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Tabby could not approve this payment. "
                            "Try another payment mode or contact your sales agent."
                        ),
                    ) from exc
                raise HTTPException(
                    status_code=400,
                    detail="Could not start Tabby checkout. Please try again or ask for a new payment link.",
                ) from exc
            if is_tamara:
                raise HTTPException(
                    status_code=400,
                    detail="Could not start Tamara checkout. Please try again or ask for a new payment link.",
                ) from exc
            if "valid email" in message.lower() or "billing_data" in message.lower():
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Paymob rejected the email address. "
                        "Use a real inbox (not example.com / test.com) and try again."
                    ),
                ) from exc
            raise HTTPException(
                status_code=400,
                detail="Could not start Paymob checkout. Please try again or ask for a new payment link.",
            ) from exc

    async def _sync_registrant_to_bitrix(
        self,
        workflow: CustomerWorkflow,
        *,
        course_for: str | None = None,
        registrant_name: str | None = None,
        registrant_email: str | None = None,
        registrant_phone: str | None = None,
        participants: list[dict[str, Any]] | None = None,
    ) -> None:
        bitrix = get_bitrix_client(self.settings)
        student_name, student_email, student_phone = self._resolve_student_identity(
            course_for=course_for,
            registrant_name=registrant_name or workflow.customer_name,
            registrant_email=registrant_email or workflow.customer_email,
            registrant_phone=registrant_phone or workflow.customer_phone,
            participants=participants,
        )
        if workflow.bitrix_lead_id:
            try:
                await bitrix.sync_lead_student_details(
                    workflow.bitrix_lead_id,
                    name=student_name,
                    email=student_email,
                    phone=student_phone,
                )
            except Exception:
                logger.exception(
                    "Failed to sync student details to Bitrix lead %s",
                    workflow.bitrix_lead_id,
                )
        deal_ids = workflow.related_bitrix_deal_ids()
        for deal_id in deal_ids:
            if not deal_id:
                continue
            try:
                await bitrix.sync_deal_customer_details(
                    deal_id,
                    name=registrant_name or workflow.customer_name,
                    email=registrant_email or workflow.customer_email,
                    phone=registrant_phone or workflow.customer_phone,
                )
            except Exception:
                logger.exception("Failed to sync registrant to Bitrix deal %s", deal_id)

    @staticmethod
    def _resolve_student_identity(
        *,
        course_for: str | None,
        registrant_name: str | None,
        registrant_email: str | None,
        registrant_phone: str | None,
        participants: list[dict[str, Any]] | None,
    ) -> tuple[str | None, str | None, str | None]:
        """Student fields: self → payer; someone else → the one candidate."""
        if (course_for or "").strip() == "someone_else":
            people = [p for p in (participants or []) if isinstance(p, dict)]
            if people:
                first = people[0]
                name = str(first.get("name") or "").strip() or None
                email = str(first.get("email") or "").strip() or None
                phone = str(first.get("phone") or "").strip() or None
                return name, email, phone
        return (
            (registrant_name or "").strip() or None,
            (registrant_email or "").strip() or None,
            (registrant_phone or "").strip() or None,
        )
