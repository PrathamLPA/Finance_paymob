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
        html = markdown
        html = re.sub(r"^# (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
        html = re.sub(r"^\*\*(.+?)\*\*", r"<strong>\1</strong>", html, flags=re.MULTILINE)
        paragraphs = []
        for block in html.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            if block.startswith("<h2>"):
                paragraphs.append(block)
            else:
                paragraphs.append(f"<p>{block}</p>")
        return "\n".join(paragraphs)

    def get_terms_context(self) -> dict:
        markdown = self.load_terms_markdown()
        return {
            "terms_version": self.settings.terms_version,
            "terms_html": self.markdown_to_html(markdown),
            "refund_policy_url": self.settings.refund_policy_url,
        }

    def generate_acceptance_pdf(self, session: PaymentSession) -> str:
        pdf_dir = Path(self.settings.storage_path) / "pdfs" / "terms"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"terms_acceptance_{session.id}_{session.token[:8]}.pdf"

        markdown = self.load_terms_markdown()
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        c.drawString(72, 750, "Terms and Conditions — Acceptance Record")
        c.drawString(72, 730, f"Version: {self.settings.terms_version}")
        c.drawString(72, 710, f"Accepted at: {datetime.now(timezone.utc).isoformat()}")
        c.drawString(72, 690, f"Session token: {session.token[:16]}...")

        y = 660
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
    ) -> str:
        if not accepted:
            raise HTTPException(status_code=400, detail="You must accept the Terms and Conditions to continue")

        session = self.session_service.get_active_session_by_token(token)
        if not session:
            raise HTTPException(status_code=404, detail="Payment session not found or expired")

        if session.status == SESSION_TERMS_ACCEPTED and session.paymob_checkout_url:
            return session.paymob_checkout_url

        pdf_path = self.generate_acceptance_pdf(session)

        acceptance = TermsAcceptance(
            payment_session_id=session.id,
            ip_address=ip_address,
            pdf_path=pdf_path,
            terms_version=self.settings.terms_version,
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
