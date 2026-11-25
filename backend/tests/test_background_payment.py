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


# --------------------------------------------------------------- durable follow-up


def _count_calls(monkeypatch, cls, name):
    calls = {"n": 0}
    original = getattr(cls, name)

    async def wrapper(self, *args, **kwargs):
        calls["n"] += 1
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(cls, name, wrapper)
    return calls


def test_finished_steps_are_not_repeated_on_a_second_run(db_session, monkeypatch):
    from app.services.invoice_service import InvoiceService

    background_jobs.reset_jobs()
    workflow, txn = _payment(db_session, lead_id=5151)
    comments = _count_calls(monkeypatch, WorkflowOrchestrator, "_comment_on_workflow_entities")
    invoices = _count_calls(monkeypatch, InvoiceService, "sync_invoice_after_payment")

    async def run_twice():
        orch = WorkflowOrchestrator(db_session, get_settings())
        for _ in range(2):
            await orch.apply_recorded_payment(
                workflow, txn, amount=Decimal("50.00"), currency="AED", finance_release=True
            )

    asyncio.run(run_twice())
    assert comments["n"] == 1
    assert invoices["n"] == 1
    db_session.refresh(txn)
    assert txn.post_state in ("done", "problem")
    assert "comment" in txn.post_steps["done"]


def test_a_failed_step_is_retried_without_redoing_the_finished_ones(db_session, monkeypatch):
    from app.services.invoice_service import InvoiceService

    workflow, txn = _payment(db_session, lead_id=5252)
    invoices = _count_calls(monkeypatch, InvoiceService, "sync_invoice_after_payment")
    original = WorkflowOrchestrator._comment_on_workflow_entities
    state = {"fail": True}

    async def flaky(self, wf, comment):
        if state["fail"]:
            raise RuntimeError("Bitrix is down")
        return await original(self, wf, comment)

    monkeypatch.setattr(WorkflowOrchestrator, "_comment_on_workflow_entities", flaky)

    async def run():
        orch = WorkflowOrchestrator(db_session, get_settings())
        await orch.apply_recorded_payment(
            workflow, txn, amount=Decimal("50.00"), currency="AED", finance_release=True
        )
        first_problems = list(orch.last_problems)
        state["fail"] = False
        await orch.apply_recorded_payment(
            workflow, txn, amount=Decimal("50.00"), currency="AED", finance_release=True
        )
        return first_problems, list(orch.last_problems)

    first, second = asyncio.run(run())
    assert any("comment" in p for p in first)
    # The comment problem is gone (the mock Bitrix never activates triggers, so that
    # one line is expected and unrelated).
    assert not any("comment" in p for p in second)
    db_session.refresh(txn)
    assert "comment" in txn.post_steps["done"]
    # The invoice finished the first time and was not created or applied again.
    assert invoices["n"] == 1


def test_recovery_resumes_a_follow_up_cut_off_by_a_restart(db_session, background_on):
    from datetime import datetime, timedelta, timezone

    from app.services.payment_followup import Checkpoints, recover_unfinished

    workflow, txn = _payment(db_session, lead_id=5353)
    Checkpoints(db_session, txn).set_meta(
        first_payment=True,
        amount="50.00",
        currency="AED",
        comment_prefix="Cash payment",
        skip_zoho=False,
        skip_deals=False,
    )
    # As if the server restarted three minutes ago while this was running.
    txn.post_state = "running"
    txn.post_updated_at = datetime.now(timezone.utc) - timedelta(minutes=3)
    db_session.commit()

    async def go():
        resumed = await recover_unfinished(get_settings())
        job = await _wait(f"payment:{txn.id}")
        return resumed, job

    resumed, job = asyncio.run(go())
    assert resumed == 1
    assert job.state in (background_jobs.STATE_DONE, background_jobs.STATE_PROBLEM)
    db_session.expire_all()
    assert db_session.get(PaymentTransaction, txn.id).post_state in ("done", "problem")


def test_recovery_leaves_recent_and_finished_work_alone(db_session, background_on):
    from datetime import datetime, timezone

    from app.services.payment_followup import Checkpoints, recover_unfinished

    _, recent = _payment(db_session, lead_id=5454)
    Checkpoints(db_session, recent).set_meta(first_payment=True, amount="50.00", currency="AED")
    recent.post_state = "running"
    recent.post_updated_at = datetime.now(timezone.utc)  # just started: still in progress
    db_session.commit()

    assert asyncio.run(recover_unfinished(get_settings())) == 0


def test_job_status_survives_a_restart(client, db_session):
    import os

    from app.models.staff_user import ROLE_MANAGER, StaffUser
    from app.services.staff_auth import hash_password

    os.environ["STAFF_JWT_SECRET"] = "test-secret-for-restart"
    get_settings.cache_clear()
    db_session.add(
        StaffUser(
            email="r@example.com",
            name="R",
            password_hash=hash_password("secret1"),
            role=ROLE_MANAGER,
            is_active=True,
        )
    )
    db_session.commit()
    token = client.post(
        "/api/staff/login", json={"email": "r@example.com", "password": "secret1"}
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    _, txn = _payment(db_session, lead_id=5555)
    txn.post_state = "problem"
    txn.post_problems = ["The Zoho invoice was not created or sent"]
    db_session.commit()
    background_jobs.reset_jobs()  # nothing in memory, as after a restart

    body = client.get(f"/api/staff/jobs/payment:{txn.id}", headers=headers).json()
    assert body["state"] == "problem"
    assert body["problems"] == ["The Zoho invoice was not created or sent"]


# --------------------------------------------------------------- manager approval link


def _approval(db, token="appr-queue-1", expired=False):
    from datetime import datetime, timedelta, timezone

    from app.models.price_approval import PriceApproval

    workflow = CustomerWorkflow(
        bitrix_lead_id=6161, customer_name="Sam", total_amount=Decimal("100.00")
    )
    db.add(workflow)
    db.commit()
    delta = timedelta(days=-1) if expired else timedelta(days=1)
    row = PriceApproval(
        workflow_id=workflow.id,
        bitrix_lead_id=6161,
        token=token,
        manager_email="m@example.com",
        total_payable="100.00",
        expires_at=datetime.now(timezone.utc) + delta,
    )
    db.add(row)
    db.commit()
    return row


def test_manager_approval_answers_at_once_and_builds_the_link_afterwards(
    client, db_session, background_on
):
    _approval(db_session)
    res = client.post("/api/approvals/appr-queue-1/approve", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "approved"
    assert body["queued"] is True
    # The manager is not handed the payment link; it is sent to the customer.
    assert body["payment_url"] is None
    assert background_jobs.get_job(f"approval:{_approval_id(db_session)}") is not None


def _approval_id(db):
    from app.models.price_approval import PriceApproval

    return db.query(PriceApproval).filter_by(token="appr-queue-1").one().id


def test_manager_approval_still_rejects_bad_links_immediately(client, db_session, background_on):
    _approval(db_session, token="appr-old", expired=True)
    assert client.post("/api/approvals/nope/approve", json={}).status_code == 400
    expired = client.post("/api/approvals/appr-old/approve", json={})
    assert expired.status_code == 400
    assert "expired" in expired.json()["detail"]
