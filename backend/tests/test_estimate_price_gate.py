"""Tests for catalog price gate + automatic Bitrix Estimate creation."""

from decimal import Decimal

import pytest

from app.config import get_settings
from app.integrations.factory import get_bitrix_client
from app.services.estimate_price_gate import evaluate_price_gate
from app.services.price_approval_service import PriceApprovalPending, PriceApprovalService
from app.services.workflow_orchestrator import WorkflowOrchestrator


def test_evaluate_price_gate_blocks_below_catalog_min():
    rows = [
        {
            "productId": 10,
            "productName": "AWS Solutions Architect",
            "price": 5500,
            "quantity": 1,
            "taxRate": 0,
            "taxIncluded": "Y",
        }
    ]
    catalog = {10: Decimal("6000.00")}
    result = evaluate_price_gate(rows, catalog)
    assert result.ok is False
    assert "below the catalog minimum" in result.reason.lower()


def test_evaluate_price_gate_passes_at_or_above_min():
    rows = [
        {
            "productId": 10,
            "productName": "AWS Solutions Architect",
            "price": 6000,
            "quantity": 1,
            "taxRate": 5,
            "taxIncluded": "N",
        }
    ]
    catalog = {10: Decimal("6000.00")}
    result = evaluate_price_gate(rows, catalog)
    assert result.ok is True
    assert result.total_payable == Decimal("6300.00")
    assert result.tax_total == Decimal("300.00")


def test_evaluate_price_gate_requires_products():
    result = evaluate_price_gate([], {})
    assert result.ok is False
    assert "no products" in result.reason.lower()


def test_evaluate_price_gate_multiple_products_flags_only_below_min():
    rows = [
        {
            "productId": 10,
            "productName": "AWS Architect",
            "price": 5000,
            "quantity": 1,
            "taxRate": 0,
            "taxIncluded": "Y",
        },
        {
            "productId": 20,
            "productName": "PMP",
            "price": 7000,
            "quantity": 1,
            "taxRate": 0,
            "taxIncluded": "Y",
        },
        {
            "productId": 30,
            "productName": "RMP",
            "price": 1000,
            "quantity": 2,
            "taxRate": 0,
            "taxIncluded": "Y",
        },
    ]
    catalog = {
        10: Decimal("6000.00"),
        20: Decimal("7000.00"),
        30: Decimal("5500.00"),
    }
    result = evaluate_price_gate(rows, catalog)
    assert result.ok is False
    assert len(result.lines) == 3
    assert len(result.blocked_lines) == 2
    blocked_names = {line.product_name for line in result.blocked_lines}
    assert blocked_names == {"AWS Architect", "RMP"}
    assert "AWS Architect" in result.reason
    assert "RMP" in result.reason
    assert "PMP" not in result.reason
    assert result.total_payable == Decimal("14000.00")
    assert result.catalog_minimum_total == Decimal("24000.00")


@pytest.mark.asyncio
async def test_manager_approval_includes_all_products_with_below_flags(db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "true")
    monkeypatch.setenv("BITRIX_APPROVAL_FALLBACK_EMAIL", "")
    get_settings.cache_clear()

    bitrix = get_bitrix_client()
    bitrix.seed_user(101, email="owner@test.com", name="Lead Owner", department_ids=[5])
    bitrix.seed_user(202, email="manager@test.com", name="Sales Manager", department_ids=[5])
    bitrix.seed_department_manager(5, 202)
    bitrix.seed_lead(901, email="multi@test.com", name="Multi Course", amount=Decimal("12000"))
    bitrix.seed_catalog_product(10, name="AWS", price=Decimal("6000"))
    bitrix.seed_catalog_product(20, name="PMP", price=Decimal("7000"))
    bitrix.seed_lead_products(
        901,
        [
            {
                "productId": 10,
                "productName": "AWS",
                "price": 5000,
                "quantity": 1,
                "taxRate": 0,
                "taxIncluded": "Y",
            },
            {
                "productId": 20,
                "productName": "PMP",
                "price": 7000,
                "quantity": 1,
                "taxRate": 0,
                "taxIncluded": "Y",
            },
        ],
    )

    orchestrator = WorkflowOrchestrator(db_session)
    with pytest.raises(PriceApprovalPending) as exc:
        await orchestrator.initiate_payment_from_lead(901)

    approval = orchestrator.approval_service.get_by_token(
        exc.value.approval_url.rsplit("/", 1)[-1]
    )
    assert approval is not None
    public = orchestrator.approval_service.to_public_dict(approval)
    assert public["product_count"] == 2
    assert public["below_minimum_count"] == 1
    assert public["ok_count"] == 1
    assert len(public["lines"]) == 2
    assert len(public["below_minimum_lines"]) == 1
    assert public["below_minimum_lines"][0]["product_name"] == "AWS"
    assert public["below_minimum_lines"][0]["discount_amount"] == "1000.00"
    assert public["ok_lines"][0]["product_name"] == "PMP"

    body = orchestrator.approval_service._email_body(approval, public["approval_url"])
    assert "Needs price approval (1):" in body
    assert "AWS" in body and "BELOW MIN" in body
    assert "At / above minimum (1):" in body
    assert "PMP" in body


@pytest.mark.asyncio
async def test_price_gate_requests_manager_approval(db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "true")
    monkeypatch.setenv("BITRIX_APPROVAL_FALLBACK_EMAIL", "")
    get_settings.cache_clear()

    bitrix = get_bitrix_client()
    bitrix.seed_user(101, email="owner@test.com", name="Lead Owner", department_ids=[5])
    bitrix.seed_user(202, email="manager@test.com", name="Sales Manager", department_ids=[5])
    bitrix.seed_department_manager(5, 202)
    bitrix.seed_lead(501, email="gate@test.com", name="Gate Test", amount=Decimal("5500"))
    bitrix.seed_catalog_product(10, name="AWS Solutions Architect", price=Decimal("6000"))
    bitrix.seed_lead_products(
        501,
        [
            {
                "productId": 10,
                "productName": "AWS Solutions Architect",
                "price": 5500,
                "quantity": 1,
                "taxRate": 0,
                "taxIncluded": "Y",
            }
        ],
    )

    orchestrator = WorkflowOrchestrator(db_session)
    with pytest.raises(PriceApprovalPending) as exc:
        await orchestrator.initiate_payment_from_lead(501)

    workflow = orchestrator.get_or_create_workflow(501)
    assert workflow.bitrix_estimate_id is not None
    assert "manager@test.com" in str(exc.value)
    assert "/approvals/" in exc.value.approval_url
    from app.integrations.factory import get_email_client

    email_client = get_email_client()
    assert email_client.sent_emails
    assert email_client.sent_emails[-1]["to"] == "manager@test.com"
    assert "Approval needed" in email_client.sent_emails[-1]["subject"]

    comments = bitrix._mock_comments.get(("LEAD", 501), [])
    assert comments
    assert any("Estimate #" in c["COMMENT"] or "Estimate already exists" in c["COMMENT"] for c in comments)
    assert any("Pending manager approval" in c["COMMENT"] for c in comments)


@pytest.mark.asyncio
async def test_failed_notification_is_retried_on_next_trigger(db_session, monkeypatch):
    """A send that failed once must not be abandoned forever."""
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "true")
    monkeypatch.setenv("BITRIX_APPROVAL_FALLBACK_EMAIL", "")
    get_settings.cache_clear()

    bitrix = get_bitrix_client()
    bitrix.seed_user(101, email="owner@test.com", name="Lead Owner", department_ids=[5])
    bitrix.seed_user(202, email="manager@test.com", name="Sales Manager", department_ids=[5])
    bitrix.seed_department_manager(5, 202)
    bitrix.seed_lead(888, email="retry@test.com", name="Retry Test", amount=Decimal("1000"))
    bitrix.seed_catalog_product(30, name="Course X", price=Decimal("5000"))
    bitrix.seed_lead_products(
        888,
        [
            {
                "productId": 30,
                "productName": "Course X",
                "price": 1000,
                "quantity": 1,
                "taxRate": 0,
                "taxIncluded": "Y",
            }
        ],
    )

    async def no_channel_available(self, approval, approval_url):
        return []

    monkeypatch.setattr(PriceApprovalService, "_notify_manager", no_channel_available)

    orchestrator = WorkflowOrchestrator(db_session)
    with pytest.raises(PriceApprovalPending):
        await orchestrator.initiate_payment_from_lead(888)

    approval = orchestrator.approval_service.get_pending_for_lead(888)
    assert approval is not None
    assert approval.notified_at is None

    # Channel is available again; the next trigger must retry the delivery via SendGrid.
    monkeypatch.undo()
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "true")
    get_settings.cache_clear()
    from app.integrations.factory import get_email_client

    email_client = get_email_client()
    sent_before = len(email_client.sent_emails)

    with pytest.raises(PriceApprovalPending):
        await orchestrator.initiate_payment_from_lead(888)

    assert len(email_client.sent_emails) == sent_before + 1
    assert "Approval needed" in email_client.sent_emails[-1]["subject"]
    db_session.refresh(approval)
    assert approval.notified_at is not None
    assert approval.notified_via == "sendgrid"

    # Approvals delivered by the old release only had Bitrix chat recorded.
    # Reusing one must send SendGrid once without repeating chat.
    approval.notified_via = "bitrix_chat"
    db_session.commit()
    sent_before = len(email_client.sent_emails)

    with pytest.raises(PriceApprovalPending):
        await orchestrator.initiate_payment_from_lead(888)

    assert len(email_client.sent_emails) == sent_before + 1
    db_session.refresh(approval)
    assert approval.notified_via == "bitrix_chat+sendgrid"

    # Once SendGrid is recorded, later automation triggers must not resend it.
    with pytest.raises(PriceApprovalPending):
        await orchestrator.initiate_payment_from_lead(888)
    assert len(email_client.sent_emails) == sent_before + 1


@pytest.mark.asyncio
async def test_pending_approval_does_not_recomment_on_rerun(db_session, monkeypatch):
    """Re-posting an identical comment retriggers the Bitrix webhook and loops."""
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "true")
    monkeypatch.setenv("BITRIX_APPROVAL_FALLBACK_EMAIL", "")
    get_settings.cache_clear()

    bitrix = get_bitrix_client()
    bitrix.seed_user(101, email="owner@test.com", name="Lead Owner", department_ids=[5])
    bitrix.seed_user(202, email="manager@test.com", name="Sales Manager", department_ids=[5])
    bitrix.seed_department_manager(5, 202)
    bitrix.seed_lead(777, email="loop@test.com", name="Loop Test", amount=Decimal("0"))
    bitrix.seed_catalog_product(20, name="RMP-PMI", price=Decimal("5500"))
    bitrix.seed_lead_products(
        777,
        [
            {
                "productId": 20,
                "productName": "RMP-PMI",
                "price": 0,
                "quantity": 1,
                "taxRate": 0,
                "taxIncluded": "Y",
            }
        ],
    )

    orchestrator = WorkflowOrchestrator(db_session)
    for _ in range(3):
        with pytest.raises(PriceApprovalPending):
            await orchestrator.initiate_payment_from_lead(777)

    comments = bitrix._mock_comments.get(("LEAD", 777), [])
    estimate_comments = [
        c
        for c in comments
        if "Estimate #" in c["COMMENT"] or "Estimate already exists" in c["COMMENT"]
    ]
    assert len(estimate_comments) == 1, (
        f"expected one estimate comment across 3 runs, got {len(estimate_comments)}"
    )


@pytest.mark.asyncio
async def test_manager_approval_sends_payment_link(db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "true")
    get_settings.cache_clear()

    bitrix = get_bitrix_client()
    bitrix.seed_user(101, email="owner@test.com", name="Lead Owner", department_ids=[5])
    bitrix.seed_user(202, email="manager@test.com", name="Sales Manager", department_ids=[5])
    bitrix.seed_department_manager(5, 202)
    bitrix.seed_lead(503, email="ok@test.com", name="Ok Test", amount=Decimal("5500"))
    bitrix.seed_catalog_product(10, name="AWS Solutions Architect", price=Decimal("6000"))
    bitrix.seed_lead_products(
        503,
        [
            {
                "productId": 10,
                "productName": "AWS Solutions Architect",
                "price": 5500,
                "quantity": 1,
                "taxRate": 0,
                "taxIncluded": "Y",
            }
        ],
    )

    orchestrator = WorkflowOrchestrator(db_session)
    with pytest.raises(PriceApprovalPending) as pending:
        await orchestrator.initiate_payment_from_lead(503)

    token = pending.value.approval_url.rsplit("/", 1)[-1]
    session = await orchestrator.complete_approved_payment(token, note="Approved for key account")

    workflow = orchestrator.get_or_create_workflow(503)
    assert workflow.bitrix_estimate_id is not None
    assert workflow.total_amount == Decimal("5500.00")
    assert session.token
    assert any("APPROVED" in c["COMMENT"] for c in bitrix._mock_comments.get(("LEAD", 503), []))
    assert any("Payment link:" in c["COMMENT"] for c in bitrix._mock_comments.get(("LEAD", 503), []))


@pytest.mark.asyncio
async def test_manager_rejection_notifies_lead_owner(db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "true")
    monkeypatch.setenv("BITRIX_APPROVAL_FALLBACK_EMAIL", "")
    get_settings.cache_clear()

    bitrix = get_bitrix_client()
    bitrix.seed_user(101, email="owner@test.com", name="Lead Owner", department_ids=[5])
    bitrix.seed_user(202, email="manager@test.com", name="Sales Manager", department_ids=[5])
    bitrix.seed_department_manager(5, 202)
    bitrix.seed_lead(504, email="reject@test.com", name="Reject Test", amount=Decimal("5500"))
    bitrix.seed_catalog_product(10, name="AWS Solutions Architect", price=Decimal("6000"))
    bitrix.seed_lead_products(
        504,
        [
            {
                "productId": 10,
                "productName": "AWS Solutions Architect",
                "price": 5500,
                "quantity": 1,
                "taxRate": 0,
                "taxIncluded": "Y",
            }
        ],
    )

    orchestrator = WorkflowOrchestrator(db_session)
    with pytest.raises(PriceApprovalPending) as pending:
        await orchestrator.initiate_payment_from_lead(504)

    token = pending.value.approval_url.rsplit("/", 1)[-1]
    await orchestrator.reject_price_approval(
        token,
        note="Raise the selling price",
        product_prices=[{"product_id": 10, "selling_price": Decimal("6000.00")}],
    )

    comments = bitrix._mock_comments.get(("LEAD", 504), [])
    assert any("REJECTED by manager" in c["COMMENT"] for c in comments)
    assert any("Responsible person" in c["COMMENT"] for c in comments)
    assert any("preferred 6000.00" in c["COMMENT"] for c in comments)
    assert any(
        n["user_id"] == 101
        and "Payment approval rejected" in n["message"]
        and "preferred 6000.00" in n["message"]
        for n in bitrix._mock_notifications
    )
    from app.integrations.factory import get_email_client

    emails = get_email_client().sent_emails
    assert any(
        e["to"] == "owner@test.com"
        and "Payment approval rejected" in e["subject"]
        and "preferred 6000.00" in e["body"]
        for e in emails
    )


@pytest.mark.asyncio
async def test_price_gate_creates_estimate_and_payment_link(db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "true")
    get_settings.cache_clear()

    bitrix = get_bitrix_client()
    bitrix.seed_lead(502, email="ok@test.com", name="Ok Test", amount=Decimal("6000"))
    bitrix.seed_catalog_product(10, name="AWS Solutions Architect", price=Decimal("6000"))
    bitrix.seed_lead_products(
        502,
        [
            {
                "productId": 10,
                "productName": "AWS Solutions Architect",
                "price": 6500,
                "quantity": 1,
                "taxRate": 0,
                "taxIncluded": "Y",
            }
        ],
    )

    orchestrator = WorkflowOrchestrator(db_session)
    session = await orchestrator.initiate_payment_from_lead(502)

    workflow = orchestrator.get_or_create_workflow(502)
    assert workflow.bitrix_estimate_id is not None
    assert workflow.total_amount == Decimal("6500.00")
    assert session.token
    assert workflow.bitrix_estimate_id in bitrix._mock_estimates

    comments = bitrix._mock_comments.get(("LEAD", 502), [])
    assert any("Estimate #" in c["COMMENT"] for c in comments)
    assert any("Payment link:" in c["COMMENT"] for c in comments)
