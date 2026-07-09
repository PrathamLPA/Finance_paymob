"""Terms and conditions acceptance flow."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.factory import get_email_client
from app.models.payment_session import PaymentSession, SESSION_TERMS_ACCEPTED
from app.models.terms_acceptance import TermsAcceptance
from app.services.payment_session_service import PaymentSessionService


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
        c.drawString(72, 650, f"Name: {registrant_name[:70]}")
        c.drawString(72, 630, f"Email: {registrant_email[:70]}")
        c.drawString(72, 610, f"Phone: {registrant_phone[:70]}")

        y = 580
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

        if session.status == SESSION_TERMS_ACCEPTED and session.paymob_checkout_url:
            return await self.session_service.refresh_paymob_checkout(session)

        pdf_path = self.generate_acceptance_pdf(
            session,
            course_for=course_for,
            registrant_name=registrant_name.strip(),
            registrant_email=registrant_email.strip(),
            registrant_phone=registrant_phone.strip(),
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
        )
        self.db.add(acceptance)
        self.session_service.mark_terms_accepted(session)

        workflow = session.workflow
        if workflow.customer_email:
            self.email.send_terms_acceptance(
                to_email=workflow.customer_email,
                customer_name=workflow.customer_name,
                pdf_path=pdf_path,
                terms_version=self.settings.terms_version,
            )

        if not session.paymob_checkout_url:
            raise HTTPException(status_code=500, detail="Payment checkout URL not available")

        return session.paymob_checkout_url
