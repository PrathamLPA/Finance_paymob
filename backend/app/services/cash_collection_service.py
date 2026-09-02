"""Cash collection queue, claim/collect, deposits, and staff ledger helpers."""

from __future__ import annotations

import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, get_settings
from app.models.cash_collection import (
    STATUS_CANCELLED,
    STATUS_CLAIMED,
    STATUS_COLLECTED,
    STATUS_OPEN,
    CashCollection,
)
from app.models.cash_deposit import CashDeposit
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_transaction import PaymentTransaction
from app.models.staff_user import ROLE_EMPLOYEE, ROLE_MANAGER, StaffUser
from app.services.installment_plan import (
    charge_installment_number_for_workflow,
    resolve_first_charge_for_workflow,
)
from app.services.staff_auth import hash_password

logger = logging.getLogger(__name__)

ALLOWED_PROOF_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}
MAX_PROOF_BYTES = 8 * 1024 * 1024


class CashCollectionQueued(Exception):
    """Raised when payment initiation enqueues cash instead of a Paymob link."""

    def __init__(self, collection: CashCollection):
        self.collection = collection
        super().__init__(
            f"Cash collection queued for lead {collection.bitrix_lead_id} "
            f"installment {collection.installment_number} (id={collection.id})"
        )


def course_title_from_workflow(workflow: CustomerWorkflow) -> str:
    snapshot = workflow.pricing_snapshot or {}
    lines = snapshot.get("lines") or []
    names = [
        str(row.get("product_name") or "").strip()
        for row in lines
        if isinstance(row, dict) and str(row.get("product_name") or "").strip()
    ]
    if names:
        return ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
    lead = workflow.bitrix_lead_payload or {}
    title = str(lead.get("TITLE") or "").strip()
    return title or f"Lead {workflow.bitrix_lead_id}"


class CashCollectionService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()

    def _proof_dir(self) -> Path:
        path = Path(self.settings.storage_path) / "cash_proofs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_proof(
        self,
        row: CashCollection,
        *,
        filename: str,
        content_type: str | None,
        data: bytes,
        staff: StaffUser,
    ) -> CashCollection:
        if row.status == STATUS_COLLECTED:
            raise ValueError("This collection was already recorded")
        if row.status != STATUS_CLAIMED or row.claimed_by_id != staff.id:
            raise ValueError("Only the claiming employee can attach a collection photo")
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
            raise ValueError("Only JPG, PNG, WEBP, or PDF photos are allowed")

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
                logger.exception("Could not remove old cash proof %s", row.proof_path)

        row.proof_path = str(dest)
        row.proof_content_type = ctype
        row.proof_original_name = (filename or safe_name)[:255]
        self.db.commit()
        self.db.refresh(row)
        return row

    def read_proof_bytes(self, row: CashCollection) -> tuple[bytes, str, str]:
        if not row.proof_path:
            raise ValueError("No proof uploaded")
        path = Path(row.proof_path)
        if not path.is_file():
            raise ValueError("Proof file missing on disk")
        return (
            path.read_bytes(),
            row.proof_content_type or "application/octet-stream",
            row.proof_original_name or path.name,
        )

    def enqueue_from_workflow(
        self,
        workflow: CustomerWorkflow,
        *,
        lead: dict[str, Any] | None = None,
        due_amount: Decimal | None = None,
        installment_number: int | None = None,
    ) -> CashCollection:
        lead = lead or workflow.bitrix_lead_payload or {}
        number = installment_number or charge_installment_number_for_workflow(workflow) or 1
        if due_amount is None:
            plan = resolve_first_charge_for_workflow(
                workflow, lead=lead, settings=self.settings
            )
            due_amount = Decimal(plan.amount).quantize(Decimal("0.01"))

        existing = self.db.scalar(
            select(CashCollection).where(
                CashCollection.workflow_id == workflow.id,
                CashCollection.installment_number == number,
            )
        )
        if existing:
            if existing.status == STATUS_COLLECTED:
                return existing
            if existing.status == STATUS_CANCELLED:
                existing.status = STATUS_OPEN
                existing.claimed_by_id = None
                existing.claimed_at = None
                existing.collected_by_id = None
                existing.collected_at = None
                existing.collected_amount = Decimal("0.00")
            existing.due_amount = due_amount
            existing.course_title = course_title_from_workflow(workflow)
            existing.customer_name = workflow.customer_name
            existing.customer_email = workflow.customer_email
            existing.customer_phone = workflow.customer_phone
            existing.currency = workflow.currency or self.settings.default_currency
            self.db.commit()
            self.db.refresh(existing)
            return existing

        row = CashCollection(
            workflow_id=workflow.id,
            bitrix_lead_id=workflow.bitrix_lead_id,
            installment_number=number,
            course_title=course_title_from_workflow(workflow),
            customer_name=workflow.customer_name,
            customer_email=workflow.customer_email,
            customer_phone=workflow.customer_phone,
            due_amount=due_amount,
            collected_amount=Decimal("0.00"),
            currency=workflow.currency or self.settings.default_currency,
            status=STATUS_OPEN,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        logger.info(
            "Cash collection enqueued id=%s lead=%s installment=%s amount=%s",
            row.id,
            row.bitrix_lead_id,
            row.installment_number,
            row.due_amount,
        )
        return row

    def list_queue(self, *, staff: StaffUser) -> list[CashCollection]:
        stmt = (
            select(CashCollection)
            .options(
                joinedload(CashCollection.claimed_by),
                joinedload(CashCollection.collected_by),
            )
            .where(
                or_(
                    CashCollection.status == STATUS_OPEN,
                    CashCollection.status == STATUS_CLAIMED,
                )
            )
            .order_by(CashCollection.created_at.asc())
        )
        rows = list(self.db.scalars(stmt).unique().all())
        if staff.role == ROLE_MANAGER:
            return rows
        # Employees see open + their own claimed
        return [
            r
            for r in rows
            if r.status == STATUS_OPEN
            or (r.status == STATUS_CLAIMED and r.claimed_by_id == staff.id)
        ]

    def claim(self, collection_id: int, staff: StaffUser) -> CashCollection:
        row = self.db.get(CashCollection, collection_id)
        if not row or row.status == STATUS_CANCELLED:
            raise ValueError("Cash collection not found")
        if row.status == STATUS_COLLECTED:
            raise ValueError("Already collected")
        if row.status == STATUS_CLAIMED and row.claimed_by_id != staff.id:
            raise ValueError("Already claimed by another employee")
        if row.status == STATUS_OPEN:
            row.status = STATUS_CLAIMED
            row.claimed_by_id = staff.id
            row.claimed_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(row)
        return row

    def employee_balances(self, employee_id: int) -> dict[str, Decimal]:
        collected = self.db.scalar(
            select(func.coalesce(func.sum(CashCollection.collected_amount), 0)).where(
                CashCollection.collected_by_id == employee_id,
                CashCollection.status == STATUS_COLLECTED,
            )
        ) or Decimal("0.00")
        deposited = self.db.scalar(
            select(func.coalesce(func.sum(CashDeposit.amount), 0)).where(
                CashDeposit.employee_id == employee_id
            )
        ) or Decimal("0.00")
        collected = Decimal(collected).quantize(Decimal("0.01"))
        deposited = Decimal(deposited).quantize(Decimal("0.01"))
        on_hand = max(collected - deposited, Decimal("0.00"))
        return {
            "collected": collected,
            "deposited": deposited,
            "on_hand": on_hand,
            "left_to_deposit": on_hand,
        }

    def record_deposit(
        self,
        *,
        employee_id: int,
        amount: Decimal,
        note: str | None,
        recorded_by: StaffUser,
    ) -> CashDeposit:
        amount = Decimal(amount).quantize(Decimal("0.01"))
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        employee = self.db.get(StaffUser, employee_id)
        if not employee or not employee.is_active:
            raise ValueError("Employee not found")
        if recorded_by.role != ROLE_MANAGER and recorded_by.id != employee_id:
            raise ValueError("Employees can only deposit their own cash")
        balances = self.employee_balances(employee_id)
        if amount > balances["on_hand"]:
            raise ValueError(
                f"Deposit {amount} exceeds cash on hand {balances['on_hand']}"
            )
        row = CashDeposit(
            employee_id=employee_id,
            amount=amount,
            currency=self.settings.default_currency,
            note=(note or "").strip() or None,
            recorded_by_id=recorded_by.id,
            deposited_at=datetime.now(timezone.utc),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_deposits(self, *, employee_id: int | None = None, limit: int = 100) -> list[CashDeposit]:
        stmt = (
            select(CashDeposit)
            .options(joinedload(CashDeposit.employee), joinedload(CashDeposit.recorded_by))
            .order_by(CashDeposit.deposited_at.desc())
            .limit(limit)
        )
        if employee_id is not None:
            stmt = stmt.where(CashDeposit.employee_id == employee_id)
        return list(self.db.scalars(stmt).unique().all())

    def create_employee(self, *, email: str, name: str, password: str) -> StaffUser:
        email = email.strip().lower()
        if not email or not name.strip() or not password:
            raise ValueError("Email, name, and password are required")
        existing = self.db.scalar(select(StaffUser).where(StaffUser.email == email))
        if existing:
            raise ValueError("An account with this email already exists")
        user = StaffUser(
            email=email,
            name=name.strip(),
            password_hash=hash_password(password),
            role=ROLE_EMPLOYEE,
            is_active=True,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def list_employees(self) -> list[dict[str, Any]]:
        users = list(
            self.db.scalars(
                select(StaffUser)
                .where(StaffUser.role == ROLE_EMPLOYEE)
                .order_by(StaffUser.name.asc())
            ).all()
        )
        out: list[dict[str, Any]] = []
        for user in users:
            bal = self.employee_balances(user.id)
            out.append(
                {
                    "id": user.id,
                    "email": user.email,
                    "name": user.name,
                    "is_active": user.is_active,
                    "on_hand": str(bal["on_hand"]),
                    "deposited": str(bal["deposited"]),
                    "left_to_deposit": str(bal["left_to_deposit"]),
                    "collected": str(bal["collected"]),
                }
            )
        return out

    def patch_employee(
        self,
        employee_id: int,
        *,
        is_active: bool | None = None,
        password: str | None = None,
        name: str | None = None,
    ) -> StaffUser:
        user = self.db.get(StaffUser, employee_id)
        if not user or user.role != ROLE_EMPLOYEE:
            raise ValueError("Employee not found")
        if is_active is not None:
            user.is_active = is_active
        if password:
            user.password_hash = hash_password(password)
        if name is not None and name.strip():
            user.name = name.strip()
        self.db.commit()
        self.db.refresh(user)
        return user

    def collection_to_dict(self, row: CashCollection) -> dict[str, Any]:
        workflow = row.workflow or self.db.get(CustomerWorkflow, row.workflow_id)
        total = workflow.total_amount if workflow else Decimal("0.00")
        paid = workflow.amount_paid if workflow else Decimal("0.00")
        remaining = workflow.remaining_balance if workflow else Decimal("0.00")
        return {
            "id": row.id,
            "workflow_id": row.workflow_id,
            "bitrix_lead_id": row.bitrix_lead_id,
            "installment_number": row.installment_number,
            "course_title": row.course_title,
            "customer_name": row.customer_name,
            "customer_email": row.customer_email,
            "customer_phone": row.customer_phone,
            "due_amount": str(row.due_amount),
            "collected_amount": str(row.collected_amount),
            "currency": row.currency,
            "status": row.status,
            "claimed_by_id": row.claimed_by_id,
            "claimed_by_name": row.claimed_by.name if row.claimed_by else None,
            "collected_by_id": row.collected_by_id,
            "collected_by_name": row.collected_by.name if row.collected_by else None,
            "claimed_at": row.claimed_at.isoformat() if row.claimed_at else None,
            "collected_at": row.collected_at.isoformat() if row.collected_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "course_total": str(total),
            "amount_paid": str(paid),
            "remaining_balance": str(remaining),
            "is_collected": row.status == STATUS_COLLECTED,
            "has_proof": bool(row.proof_path),
            "proof_original_name": row.proof_original_name,
            "proof_url": (
                f"/api/staff/cash/{row.id}/proof" if row.proof_path else None
            ),
        }

    def dashboard(self) -> dict[str, Any]:
        employees = list(
            self.db.scalars(select(StaffUser).where(StaffUser.role == ROLE_EMPLOYEE)).all()
        )
        total_on_hand = Decimal("0.00")
        total_deposited = Decimal("0.00")
        for emp in employees:
            bal = self.employee_balances(emp.id)
            total_on_hand += bal["on_hand"]
            total_deposited += bal["deposited"]

        pending = self.db.scalar(
            select(func.count()).select_from(CashCollection).where(
                CashCollection.status.in_([STATUS_OPEN, STATUS_CLAIMED])
            )
        ) or 0

        cash_collected = self.db.scalar(
            select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
                PaymentTransaction.source_type == "cash"
            )
        ) or Decimal("0.00")
        online_collected = self.db.scalar(
            select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
                or_(
                    PaymentTransaction.source_type.is_(None),
                    PaymentTransaction.source_type != "cash",
                )
            )
        ) or Decimal("0.00")

        return {
            "cash_on_hand": str(Decimal(total_on_hand).quantize(Decimal("0.01"))),
            "total_deposited": str(Decimal(total_deposited).quantize(Decimal("0.01"))),
            "pending_collections": int(pending),
            "cash_collected": str(Decimal(cash_collected).quantize(Decimal("0.01"))),
            "online_collected": str(Decimal(online_collected).quantize(Decimal("0.01"))),
            "employee_count": len(employees),
        }

    def list_transactions(
        self,
        *,
        channel: str = "all",
        employee_id: int | None = None,
        q: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(PaymentTransaction)
            .options(joinedload(PaymentTransaction.workflow))
            .order_by(PaymentTransaction.paid_at.desc())
            .limit(limit)
        )
        if channel == "cash":
            stmt = stmt.where(PaymentTransaction.source_type == "cash")
        elif channel == "online":
            stmt = stmt.where(
                or_(
                    PaymentTransaction.source_type.is_(None),
                    PaymentTransaction.source_type != "cash",
                )
            )
        rows = list(self.db.scalars(stmt).unique().all())

        # Map cash txn → collector via transaction_id prefix CASH-{id}-
        collection_ids: list[int] = []
        for txn in rows:
            if txn.source_type == "cash" and txn.transaction_id.startswith("CASH-"):
                parts = txn.transaction_id.split("-")
                if len(parts) >= 2 and parts[1].isdigit():
                    collection_ids.append(int(parts[1]))
        collections_by_id: dict[int, CashCollection] = {}
        if collection_ids:
            for c in self.db.scalars(
                select(CashCollection)
                .options(joinedload(CashCollection.collected_by))
                .where(CashCollection.id.in_(collection_ids))
            ).unique():
                collections_by_id[c.id] = c

        out: list[dict[str, Any]] = []
        needle = (q or "").strip().lower()
        for txn in rows:
            wf = txn.workflow
            channel_label = "cash" if txn.source_type == "cash" else "online"
            employee_name = None
            employee_email = None
            emp_id = None
            collection_id = None
            if txn.source_type == "cash" and txn.transaction_id.startswith("CASH-"):
                parts = txn.transaction_id.split("-")
                if len(parts) >= 2 and parts[1].isdigit():
                    collection_id = int(parts[1])
                    col = collections_by_id.get(collection_id)
                    if col and col.collected_by:
                        employee_name = col.collected_by.name
                        employee_email = col.collected_by.email
                        emp_id = col.collected_by_id
            if employee_id is not None and emp_id != employee_id:
                continue
            course = course_title_from_workflow(wf) if wf else None
            customer = (wf.customer_name if wf else None) or ""
            if needle:
                hay = " ".join(
                    [
                        customer,
                        wf.customer_email or "" if wf else "",
                        course or "",
                        str(wf.bitrix_lead_id if wf else ""),
                        employee_name or "",
                    ]
                ).lower()
                if needle not in hay:
                    continue
            out.append(
                {
                    "id": txn.id,
                    "transaction_id": txn.transaction_id,
                    "workflow_id": wf.id if wf else None,
                    "channel": channel_label,
                    "amount": str(txn.amount),
                    "currency": txn.currency,
                    "paid_at": txn.paid_at.isoformat() if txn.paid_at else None,
                    "bitrix_lead_id": wf.bitrix_lead_id if wf else None,
                    "customer_name": wf.customer_name if wf else None,
                    "customer_email": wf.customer_email if wf else None,
                    "course_title": course,
                    "course_total": str(wf.total_amount) if wf else None,
                    "amount_paid": str(wf.amount_paid) if wf else None,
                    "remaining_balance": str(wf.remaining_balance) if wf else None,
                    "employee_id": emp_id,
                    "employee_name": employee_name,
                    "employee_email": employee_email,
                    "collection_id": collection_id,
                    "zoho_invoice_id": wf.zoho_invoice_id if wf else None,
                    "invoice_synced": bool(wf and wf.zoho_invoice_id),
                }
            )
        return out

    @staticmethod
    def new_cash_transaction_id(collection_id: int) -> str:
        return f"CASH-{collection_id}-{uuid.uuid4().hex[:12]}"
