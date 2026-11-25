"""Approve / Collect save the payment first and run the slow steps after the response."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.customer_workflow import CustomerWorkflow
from app.models.finance_verification import FinanceVerification
from app.models.payment_transaction import PaymentTransaction
from app.services import background_jobs
from app.services.workflow_orchestrator import WorkflowOrchestrator


@pytest.fixture
def background_on(monkeypatch, db_session):
    monkeypatch.setenv("POST_PAYMENT_BACKGROUND", "true")
    get_settings.cache_clear()
    background_jobs.reset_jobs()
    background_jobs.session_factory = sessionmaker(bind=db_session.get_bind())
    yield
    background_jobs.session_factory = None
    background_jobs.reset_jobs()
    get_settings.cache_clear()


def _payment(db, lead_id=4242):
    workflow = CustomerWorkflow(
        bitrix_lead_id=lead_id,
        customer_name="Sam",
        customer_email="sam@example.com",
        total_amount=Decimal("100.00"),
        amount_paid=Decimal("50.00"),
    )
    db.add(workflow)
    db.commit()
    txn = PaymentTransaction(
        workflow_id=workflow.id,
        transaction_id=f"CASH-{lead_id}",
        amount=Decimal("50.00"),
        remaining_balance=Decimal("50.00"),
        source_type="cash",
    )
    db.add(txn)
    db.commit()
    return workflow, txn


async def _wait(key, timeout=10.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        job = background_jobs.get_job(key)
        if job is not None and job.state != background_jobs.STATE_RUNNING:
            return job
        await asyncio.sleep(0.05)
    raise AssertionError("background job did not finish")


def test_slow_steps_run_after_the_call_returns(db_session, background_on):
    workflow, txn = _payment(db_session)

    async def go():
        orch = WorkflowOrchestrator(db_session, get_settings())
        key = await orch.apply_recorded_payment_deferred(
            workflow, txn, amount=Decimal("50.00"), currency="AED"
        )
        assert key == f"payment:{txn.id}"
        # The call returned while the job was only queued.
        assert background_jobs.get_job(key) is not None
        return await _wait(key)

    job = asyncio.run(go())
    assert job.state in (background_jobs.STATE_DONE, background_jobs.STATE_PROBLEM)
    assert job.finished_at is not None


def test_held_payment_is_not_run_in_the_background(db_session, background_on, monkeypatch):
    monkeypatch.setenv("FINANCE_MANAGER_VERIFICATION", "true")
    get_settings.cache_clear()
    workflow, txn = _payment(db_session, lead_id=4343)

    async def go():
        orch = WorkflowOrchestrator(db_session, get_settings())
        return await orch.apply_recorded_payment_deferred(
            workflow, txn, amount=Decimal("50.00"), currency="AED"
        )

    assert asyncio.run(go()) is None
    held = db_session.query(FinanceVerification).filter_by(payment_transaction_id=txn.id).one()
    assert held.status == "pending"
    assert background_jobs.get_job(f"payment:{txn.id}") is None


def test_runs_inline_when_background_is_off(db_session, monkeypatch):
    monkeypatch.setenv("POST_PAYMENT_BACKGROUND", "false")
    get_settings.cache_clear()
    background_jobs.reset_jobs()
    workflow, txn = _payment(db_session, lead_id=4444)

    async def go():
        orch = WorkflowOrchestrator(db_session, get_settings())
        return await orch.apply_recorded_payment_deferred(
            workflow, txn, amount=Decimal("50.00"), currency="AED"
        )

    assert asyncio.run(go()) is None
    assert background_jobs.get_job(f"payment:{txn.id}") is None


def test_a_crashing_job_is_reported_not_lost():
    background_jobs.reset_jobs()

    async def go():
        async def boom():
            raise RuntimeError("zoho down")

        background_jobs.spawn("payment:x", "test", boom)
        return await _wait("payment:x")

    job = asyncio.run(go())
    assert job.state == background_jobs.STATE_FAILED
    assert "zoho down" in job.problems[0]


def test_job_status_endpoint(client, db_session):
    import os

    from app.models.staff_user import ROLE_MANAGER, StaffUser
    from app.services.staff_auth import hash_password

    os.environ["STAFF_JWT_SECRET"] = "test-secret-for-jobs"
    get_settings.cache_clear()
    db_session.add(
        StaffUser(
            email="m@example.com",
            name="M",
            password_hash=hash_password("secret1"),
            role=ROLE_MANAGER,
            is_active=True,
        )
    )
    db_session.commit()
    token = client.post(
        "/api/staff/login", json={"email": "m@example.com", "password": "secret1"}
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    unknown = client.get("/api/staff/jobs/payment:999", headers=headers).json()
    assert unknown["state"] == "unknown"

    background_jobs.reset_jobs()
    job = background_jobs.Job(key="payment:7", label="x", state=background_jobs.STATE_PROBLEM)
    job.problems = ["The Zoho invoice was not created or sent"]
    background_jobs._jobs["payment:7"] = job
    body = client.get("/api/staff/jobs/payment:7", headers=headers).json()
    assert body["state"] == "problem"
    assert body["problems"] == ["The Zoho invoice was not created or sent"]
    client.cookies.clear()
    assert client.get("/api/staff/jobs/payment:7").status_code == 401
    background_jobs.reset_jobs()


def test_invoice_button_answers_at_once_and_finishes_in_background(
    client, db_session, background_on
):
    import os
    import time

    from app.models.staff_user import ROLE_MANAGER, StaffUser
    from app.services.staff_auth import hash_password

    os.environ["STAFF_JWT_SECRET"] = "test-secret-for-retrigger"
    get_settings.cache_clear()
    db_session.add(
        StaffUser(
            email="fin@example.com",
            name="Fin",
            password_hash=hash_password("secret1"),
            role=ROLE_MANAGER,
            is_active=True,
        )
    )
    db_session.commit()
    token = client.post(
        "/api/staff/login", json={"email": "fin@example.com", "password": "secret1"}
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    workflow, txn = _payment(db_session, lead_id=4545)

    res = client.post(
        "/api/staff/invoices/retrigger",
        headers=headers,
        json={"payment_transaction_id": txn.id},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["queued"] is True
    key = body["job"]
    assert key == f"invoice:{txn.id}"

    state = "running"
    for _ in range(100):
        state = client.get(f"/api/staff/jobs/{key}", headers=headers).json()["state"]
        if state != "running":
            break
        time.sleep(0.05)
    assert state in ("done", "problem")
