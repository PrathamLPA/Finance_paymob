"""Bank transfer: payment-session enqueue, receipt upload, finance approve/reject."""

from __future__ import annotations

import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, get_settings
from app.models.bank_transfer import (
    STATUS_APPROVED,
    STATUS_AWAITING_UPLOAD,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    BankTransferSubmission,
)
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import (
    SESSION_COMPLETED,
    SESSION_TERMS_ACCEPTED,
    PaymentSession,
)
from app.models.payment_transaction import PaymentTransaction
from app.models.staff_user import StaffUser
from app.services.cash_collection_service import course_title_from_workflow

logger = logging.getLogger(__name__)

ALLOWED_PROOF_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "application/pdf",
}
MAX_PROOF_BYTES = 8 * 1024 * 1024


class BankTransferService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()

    def _proof_dir(self) -> Path:
        root = Path(self.settings.storage_path)
        path = root / "bank_transfers"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def enqueue_for_session(
        self,
        session: PaymentSession,
        *,
        lead: dict[str, Any] | None = None,
    ) -> BankTransferSubmission:
        workflow = session.workflow or self.db.get(CustomerWorkflow, session.workflow_id)
        if not workflow:
            raise ValueError("Workflow not found for payment session")
        number = session.installment_number or 1
        due = Decimal(session.charge_amount).quantize(Decimal("0.01"))

        existing = self.db.scalar(
            select(BankTransferSubmission).where(
                BankTransferSubmission.workflow_id == workflow.id,
                BankTransferSubmission.installment_number == number,
            )
        )
        if existing:
            if existing.status == STATUS_APPROVED:
                return existing
            existing.payment_session_id = session.id
            existing.due_amount = due
            existing.currency = session.currency or workflow.currency
            existing.course_title = course_title_from_workflow(workflow)
            existing.customer_name = workflow.customer_name
            existing.customer_email = workflow.customer_email
            existing.customer_phone = workflow.customer_phone
            existing.bitrix_estimate_id = workflow.bitrix_estimate_id
            if existing.status in (STATUS_REJECTED, STATUS_AWAITING_UPLOAD):
                existing.status = STATUS_AWAITING_UPLOAD
                existing.reviewed_by_id = None
                existing.reviewed_at = None
                existing.review_note = None
            self.db.commit()
            self.db.refresh(existing)
            return existing

        row = BankTransferSubmission(
            workflow_id=workflow.id,
            payment_session_id=session.id,
            bitrix_lead_id=workflow.bitrix_lead_id,
            bitrix_estimate_id=workflow.bitrix_estimate_id,
            installment_number=number,
            course_title=course_title_from_workflow(workflow),
            customer_name=workflow.customer_name,
            customer_email=workflow.customer_email,
            customer_phone=workflow.customer_phone,
            due_amount=due,
            currency=session.currency or workflow.currency or self.settings.default_currency,
            status=STATUS_AWAITING_UPLOAD,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        logger.info(
            "Bank transfer enqueued id=%s lead=%s installment=%s session=%s",
            row.id,
            row.bitrix_lead_id,
            row.installment_number,
            session.id,
        )
        return row

    def get_by_session(self, session: PaymentSession) -> BankTransferSubmission | None:
        return self.db.scalar(
            select(BankTransferSubmission).where(
                BankTransferSubmission.payment_session_id == session.id
            )
        ) or self.db.scalar(
            select(BankTransferSubmission).where(
                BankTransferSubmission.workflow_id == session.workflow_id,
                BankTransferSubmission.installment_number
                == (session.installment_number or 1),
            )
        )

    def list_for_manager(
        self, *, status: str | None = None, limit: int = 200
    ) -> list[BankTransferSubmission]:
        stmt = (
            select(BankTransferSubmission)
            .options(
                joinedload(BankTransferSubmission.reviewed_by),
                joinedload(BankTransferSubmission.payment_session).joinedload(
                    PaymentSession.terms_acceptance
                ),
                joinedload(BankTransferSubmission.workflow),
            )
            .order_by(BankTransferSubmission.created_at.desc())
            .limit(limit)
        )
        if status:
            stmt = stmt.where(BankTransferSubmission.status == status)
        else:
            stmt = stmt.where(
                or_(
                    BankTransferSubmission.status == STATUS_PENDING_REVIEW,
                    BankTransferSubmission.status == STATUS_AWAITING_UPLOAD,
                    BankTransferSubmission.status == STATUS_REJECTED,
                )
            )
        return list(self.db.scalars(stmt).unique().all())

    def submission_to_dict(self, row: BankTransferSubmission) -> dict[str, Any]:
        workflow = row.workflow or self.db.get(CustomerWorkflow, row.workflow_id)
        session = row.payment_session
        terms = session.terms_acceptance if session else None
        total = workflow.total_amount if workflow else Decimal("0.00")
        paid = workflow.amount_paid if workflow else Decimal("0.00")
        remaining = workflow.remaining_balance if workflow else Decimal("0.00")
        return {
            "id": row.id,
            "workflow_id": row.workflow_id,
            "payment_session_id": row.payment_session_id,
            "bitrix_lead_id": row.bitrix_lead_id,
            "bitrix_estimate_id": row.bitrix_estimate_id,
            "installment_number": row.installment_number,
            "course_title": row.course_title,
            "customer_name": row.customer_name,
            "customer_email": row.customer_email,
            "customer_phone": row.customer_phone,
            "due_amount": str(row.due_amount),
            "currency": row.currency,
            "status": row.status,
            "proof_original_name": row.proof_original_name,
            "proof_content_type": row.proof_content_type,
            "has_proof": bool(row.proof_path),
            "proof_url": f"/api/staff/bank-transfers/{row.id}/proof" if row.proof_path else None,
            "reviewed_by_id": row.reviewed_by_id,
            "reviewed_by_name": row.reviewed_by.name if row.reviewed_by else None,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "review_note": row.review_note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "course_total": str(total),
            "amount_paid": str(paid),
            "remaining_balance": str(remaining),
            "registrant_name": (terms.registrant_name if terms else None) or row.customer_name,
            "registrant_email": (terms.registrant_email if terms else None) or row.customer_email,
            "registrant_phone": (terms.registrant_phone if terms else None) or row.customer_phone,
            "course_for": terms.course_for if terms else None,
            "session_token": session.token if session else None,
        }

    def save_proof(
        self,
        row: BankTransferSubmission,
        *,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> BankTransferSubmission:
        if row.status == STATUS_APPROVED:
            raise ValueError("This bank transfer was already approved")
        if not data:
            raise ValueError("Empty file")
        if len(data) > MAX_PROOF_BYTES:
            raise ValueError("File too large (max 8MB)")
        ctype = (content_type or "").split(";")[0].strip().lower()
        if not ctype:
            guessed, _ = mimetypes.guess_type(filename)
            ctype = (guessed or "").lower()
        if ctype == "image/jpg":
            ctype = "image/jpeg"
        if ctype not in ALLOWED_PROOF_TYPES:
            raise ValueError("Only JPG, PNG, WEBP, or PDF receipts are allowed")

        ext = Path(filename).suffix.lower()
        if not ext:
            ext = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "application/pdf": ".pdf",
            }.get(ctype, ".bin")
        safe_name = f"{row.id}_{uuid.uuid4().hex[:12]}{ext}"
        dest = self._proof_dir() / safe_name
        dest.write_bytes(data)

        if row.proof_path:
            try:
                old = Path(row.proof_path)
                if old.is_file() and old.resolve().parent == self._proof_dir().resolve():
                    old.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not remove old bank transfer proof %s", row.proof_path)

        row.proof_path = str(dest)
        row.proof_content_type = ctype
        row.proof_original_name = (filename or safe_name)[:255]
        row.status = STATUS_PENDING_REVIEW
        row.reviewed_by_id = None
        row.reviewed_at = None
        row.review_note = None
        # Refresh customer snapshot from workflow (Terms may have updated it)
        workflow = row.workflow or self.db.get(CustomerWorkflow, row.workflow_id)
        if workflow:
            row.customer_name = workflow.customer_name
            row.customer_email = workflow.customer_email
            row.customer_phone = workflow.customer_phone
            row.course_title = course_title_from_workflow(workflow)
            row.bitrix_estimate_id = workflow.bitrix_estimate_id
        self.db.commit()
        self.db.refresh(row)
        return row

    def read_proof_bytes(self, row: BankTransferSubmission) -> tuple[bytes, str, str]:
        if not row.proof_path:
            raise ValueError("No proof uploaded")
        path = Path(row.proof_path)
        if not path.is_file():
            raise ValueError("Proof file missing on disk")
        data = path.read_bytes()
        ctype = row.proof_content_type or "application/octet-stream"
        name = row.proof_original_name or path.name
        return data, ctype, name

    async def notify_proof_submitted(self, row: BankTransferSubmission) -> None:
        from app.integrations.factory import get_bitrix_client
        from app.services.workflow_orchestrator import WorkflowOrchestrator

        workflow = row.workflow or self.db.get(CustomerWorkflow, row.workflow_id)
        if not workflow:
            return

        bitrix = get_bitrix_client(self.settings)
        comment = (
            f"Bank transfer receipt submitted â€” awaiting finance approval\n"
            f"Installment {row.installment_number}: {row.due_amount} {row.currency}\n"
            f"Customer: {row.customer_name or '-'}\n"
            f"Email: {row.customer_email or '-'}\n"
            f"Course: {row.course_title or '-'}\n"
            f"File: {row.proof_original_name or '-'}"
        )

        files: list[tuple[str, bytes]] | None = None
        try:
            data, _ctype, name = self.read_proof_bytes(row)
            files = [(name, data)]
        except ValueError:
            files = None

        try:
            lead_comment_id = await bitrix.add_timeline_comment(
                entity_type="LEAD",
                entity_id=row.bitrix_lead_id,
                comment=comment,
                files=files,
            )
            row.bitrix_lead_comment_id = lead_comment_id
        except Exception:
            logger.exception(
                "Failed bank transfer timeline comment on lead %s", row.bitrix_lead_id
            )

        estimate_id = row.bitrix_estimate_id or workflow.bitrix_estimate_id
        if estimate_id:
            try:
                est_comment_id = await bitrix.add_timeline_comment(
                    entity_type="quote",
                    entity_id=int(estimate_id),
                    comment=comment,
                    files=files,
                )
                row.bitrix_estimate_comment_id = est_comment_id
                row.bitrix_estimate_id = int(estimate_id)
            except Exception:
                logger.exception(
                    "Failed bank transfer timeline comment on estimate %s", estimate_id
                )

        self.db.commit()

        orchestrator = WorkflowOrchestrator(self.db, self.settings)
        subject = (
            f"Bank transfer receipt submitted â€” Lead #{workflow.bitrix_lead_id}"
        )
        body = (
            f"{comment}\n\n"
            f"Please review the timeline on the lead"
            + (f" / estimate #{estimate_id}" if estimate_id else "")
            + ". Finance will approve in Cash Desk."
        )
        await orchestrator._notify_assigned_agent(workflow, subject=subject, body=body)

    @staticmethod
    def new_transaction_id(submission_id: int) -> str:
        return f"BT-{submission_id}-{uuid.uuid4().hex[:12]}"

    async def approve(
        self,
        submission_id: int,
        *,
        staff: StaffUser,
        note: str | None = None,
        amount: Decimal | None = None,
    ) -> BankTransferSubmission:
        from app.services.workflow_orchestrator import WorkflowOrchestrator

        row = self.db.get(BankTransferSubmission, submission_id)
        if not row:
            raise ValueError("Bank transfer submission not found")
        if row.status == STATUS_APPROVED:
            raise ValueError("Already approved")
        if row.status != STATUS_PENDING_REVIEW:
            raise ValueError("Receipt must be submitted before approval")
        if not row.proof_path:
            raise ValueError("No receipt on file")

        approve_amount = Decimal(amount if amount is not None else row.due_amount).quantize(
            Decimal("0.01")
        )
        if approve_amount <= 0:
            raise ValueError("Amount must be positive")
        if approve_amount > row.due_amount:
            raise ValueError(f"Cannot approve more than due amount {row.due_amount}")

        workflow = self.db.get(CustomerWorkflow, row.workflow_id)
        if not workflow:
            raise ValueError("Workflow not found")

        txn_id = self.new_transaction_id(row.id)
        existing = self.db.scalar(
            select(PaymentTransaction).where(PaymentTransaction.transaction_id == txn_id)
        )
        if existing:
            raise ValueError("Duplicate bank transfer transaction")

        workflow.amount_paid += approve_amount
        remaining = workflow.remaining_balance
        transaction = PaymentTransaction(
            workflow_id=workflow.id,
            payment_session_id=row.payment_session_id,
            transaction_id=txn_id,
            order_id=None,
            amount=approve_amount,
            currency=row.currency or workflow.currency,
            remaining_balance=remaining,
            raw_payload=None,
            source_type="bank_transfer",
            success=True,
            pending=False,
        )
        self.db.add(transaction)

        row.status = STATUS_APPROVED
        row.reviewed_by_id = staff.id
        row.reviewed_at = datetime.now(timezone.utc)
        row.review_note = (note or "").strip() or None

        if row.payment_session_id:
            session = self.db.get(PaymentSession, row.payment_session_id)
            if session and session.status != SESSION_COMPLETED:
                session.status = SESSION_COMPLETED
                session.completed_at = datetime.now(timezone.utc)

        self.db.flush()

        course = row.course_title or course_title_from_workflow(workflow)
        comment_prefix = (
            f"Bank transfer payment approved via Cash Desk\n"
            f"Approved by: {staff.name} ({staff.email})\n"
            f"Course: {course}\n"
            f"Installment {row.installment_number}\n"
            f"Receipt: {row.proof_original_name or '-'}"
        )
        if row.review_note:
            comment_prefix += f"\nNote: {row.review_note}"

        orchestrator = WorkflowOrchestrator(self.db, self.settings)
        await orchestrator.apply_recorded_payment(
            workflow,
            transaction,
            amount=approve_amount,
            currency=row.currency or workflow.currency,
            comment_prefix=comment_prefix,
        )
        self.db.refresh(row)
        return row

    async def reject(
        self,
        submission_id: int,
        *,
        staff: StaffUser,
        note: str | None = None,
    ) -> BankTransferSubmission:
        from app.integrations.factory import get_bitrix_client
        from app.integrations.factory import get_email_client
        from app.services.workflow_orchestrator import WorkflowOrchestrator

        row = self.db.get(BankTransferSubmission, submission_id)
        if not row:
            raise ValueError("Bank transfer submission not found")
        if row.status == STATUS_APPROVED:
            raise ValueError("Already approved â€” cannot reject")
        if row.status not in (STATUS_PENDING_REVIEW, STATUS_AWAITING_UPLOAD, STATUS_REJECTED):
            raise ValueError("Cannot reject this submission")

        row.status = STATUS_REJECTED
        row.reviewed_by_id = staff.id
        row.reviewed_at = datetime.now(timezone.utc)
        row.review_note = (note or "").strip() or None
        self.db.commit()
        self.db.refresh(row)

        workflow = row.workflow or self.db.get(CustomerWorkflow, row.workflow_id)
        session = row.payment_session
        payment_url = None
        if session:
            from app.services.payment_session_service import PaymentSessionService

            # Allow re-upload: keep session active / reopen terms_accepted
            if session.status == SESSION_COMPLETED:
                session.status = SESSION_TERMS_ACCEPTED
                session.completed_at = None
                self.db.commit()
            payment_url = PaymentSessionService(self.db, self.settings).build_receipt_upload_url(
                session.token
            )

        reason = row.review_note or "Please upload a clearer receipt."
        comment = (
            f"Bank transfer receipt rejected by finance\n"
            f"By: {staff.name}\n"
            f"Reason: {reason}\n"
        )
        if payment_url:
            comment += f"Re-upload link: {payment_url}"

        bitrix = get_bitrix_client(self.settings)
        try:
            await bitrix.add_timeline_comment(
                entity_type="LEAD",
                entity_id=row.bitrix_lead_id,
                comment=comment,
            )
        except Exception:
            logger.exception("Failed reject comment on lead %s", row.bitrix_lead_id)

        if workflow:
            orchestrator = WorkflowOrchestrator(self.db, self.settings)
            await orchestrator._notify_assigned_agent(
                workflow,
                subject=f"Bank transfer rejected â€” Lead #{row.bitrix_lead_id}",
                body=comment,
            )
            if workflow.customer_email and payment_url:
                try:
                    email = get_email_client(self.settings)
                    email.send_payment_request(
                        to_email=workflow.customer_email,
                        customer_name=workflow.customer_name or "Customer",
                        payment_url=payment_url,
                    )
                except Exception:
                    logger.exception(
                        "Failed to email candidate after bank transfer reject lead=%s",
                        row.bitrix_lead_id,
                    )

        return row
