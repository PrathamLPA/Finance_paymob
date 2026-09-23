"""B2C Ops cards: one deal per Sales course unit."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from app.integrations.bitrix import MockBitrixClient, expand_product_units
from app.integrations.factory import get_bitrix_client
from app.models.customer_workflow import CustomerWorkflow
from tests.conftest import SAMPLE_REGISTRANT


def test_expand_product_units_by_quantity():
    rows = [
        {"productId": 1, "productName": "A", "price": "100", "quantity": 1},
        {"productId": 2, "PRODUCT_NAME": "B", "PRICE": "200", "QUANTITY": 2},
    ]
    units = expand_product_units(rows)
    assert len(units) == 3
    assert all(u.get("quantity") == 1 or u.get("QUANTITY") == 1 for u in units)
    names = [
        u.get("productName") or u.get("PRODUCT_NAME") for u in units
    ]
    assert names.count("A") == 1
    assert names.count("B") == 2


def test_create_b2c_ops_deals_one_per_unit():
    bitrix = MockBitrixClient()
    bitrix.settings.bitrix_b2c_pipeline_id = "42"
    bitrix.settings.bitrix_field_original_deal_id = "UF_CRM_ORIGINAL_DEAL_ID"
    bitrix.seed_lead(501, email="ops@test.com", name="Ops Student", amount=Decimal("5000"))
    bitrix.seed_lead_products(
        501,
        [
            {"productId": 11, "productName": "Course A", "price": "1000", "quantity": 1},
            {"productId": 22, "productName": "Course B", "price": "2000", "quantity": 2},
        ],
    )
    sales_id = asyncio.run(
        bitrix.convert_lead_to_sales_deal(501, {"currency": "AED", "total_amount": "5000"})
    )
    ids = asyncio.run(
        bitrix.create_b2c_ops_deals_from_sales(
            sales_deal_id=sales_id,
            lead_id=501,
            context={"currency": "AED"},
        )
    )
    assert len(ids) == 3
    for deal_id in ids:
        deal = bitrix._mock_deals[deal_id]
        assert str(deal.get("CATEGORY_ID")) == "42"
        assert deal.get("LEAD_ID") == 501
        assert deal.get("UF_CRM_ORIGINAL_DEAL_ID") == sales_id
        rows = bitrix._mock_product_rows.get(("D", deal_id), [])
        assert len(rows) == 1
        assert int(rows[0].get("quantity") or rows[0].get("QUANTITY") or 0) == 1
    titles = [bitrix._mock_deals[i]["TITLE"] for i in ids]
    assert sum("Course A" in t for t in titles) == 1
    assert sum("Course B" in t for t in titles) == 2


def test_create_b2c_ops_skipped_without_pipeline():
    bitrix = MockBitrixClient()
    bitrix.settings.bitrix_b2c_pipeline_id = ""
    bitrix.seed_lead(502, email="nopipe@test.com", name="No Pipe", amount=Decimal("1000"))
    sales_id = asyncio.run(bitrix.convert_lead_to_sales_deal(502, {}))
    ids = asyncio.run(
        bitrix.create_b2c_ops_deals_from_sales(
            sales_deal_id=sales_id, lead_id=502, context={}
        )
    )
    assert ids == []


def test_first_payment_creates_b2c_ops_per_unit(client, seed_lead, db_session):
    from sqlalchemy import select

    from app.config import get_settings
    from app.models.payment_session import PaymentSession

    seed_lead(503, email="split@test.com", amount=Decimal("10000"))
    bitrix = get_bitrix_client()
    get_settings().bitrix_backend_b2c_ops_split = True
    bitrix.settings.bitrix_backend_b2c_ops_split = True
    bitrix.settings.bitrix_b2c_pipeline_id = "99"
    bitrix.settings.bitrix_invoice_sent_trigger_url = (
        "https://bitrix.test/rest/crm.automation.trigger/?target=LEAD_{{ID}}&code=test"
    )
    bitrix.seed_lead_products(
        503,
        [
            {"productId": 1, "productName": "Python", "price": "4000", "quantity": 1},
            {"productId": 2, "productName": "Excel", "price": "3000", "quantity": 2},
        ],
    )

    link = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 503, "customer_email": "split@test.com", "total_amount": "10000"},
    )
    token = link.json()["token"]
    client.post(
        f"/api/payment/{token}/accept",
        json={"accepted": True, **SAMPLE_REGISTRANT},
    )
    session = db_session.scalar(select(PaymentSession).where(PaymentSession.token == token))
    assert session is not None
    merchant_reference = session.merchant_reference
    db_session.expire_all()

    payment = client.post(
        "/api/dev/simulate-paymob-webhook",
        json={"merchant_reference": merchant_reference, "amount": "5000"},
    )
    assert payment.status_code == 200
    data = payment.json()
    assert data["sales_deal_id"] == bitrix.MOCK_SALES_DEAL_BASE + 503
    assert data["b2c_deal_id"] is not None

    workflow = db_session.scalar(
        select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 503)
    )
    assert workflow is not None
    assert workflow.b2c_deal_ids is not None
    assert len(workflow.b2c_deal_ids) == 3
    assert workflow.b2c_deal_id == workflow.b2c_deal_ids[0]

    # Idempotent: second convert path must not duplicate cards.
    from app.services.workflow_orchestrator import WorkflowOrchestrator

    orch = WorkflowOrchestrator(db_session)
    before = list(workflow.b2c_deal_ids)
    asyncio.run(orch._convert_lead_to_sales_after_first_payment(workflow))
    db_session.refresh(workflow)
    assert workflow.b2c_deal_ids == before


def test_b2c_ops_split_skipped_when_flag_false(client, seed_lead, db_session):
    from sqlalchemy import select

    from app.config import get_settings
    from app.models.payment_session import PaymentSession

    seed_lead(504, email="nosplit@test.com", amount=Decimal("5000"))
    bitrix = get_bitrix_client()
    get_settings().bitrix_backend_b2c_ops_split = False
    bitrix.settings.bitrix_backend_b2c_ops_split = False
    bitrix.settings.bitrix_b2c_pipeline_id = "99"
    bitrix.settings.bitrix_invoice_sent_trigger_url = (
        "https://bitrix.test/rest/crm.automation.trigger/?target=LEAD_{{ID}}&code=test"
    )
    bitrix.seed_lead_products(
        504,
        [{"productId": 1, "productName": "Only", "price": "5000", "quantity": 2}],
    )

    link = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 504, "customer_email": "nosplit@test.com", "total_amount": "5000"},
    )
    token = link.json()["token"]
    client.post(
        f"/api/payment/{token}/accept",
        json={"accepted": True, **SAMPLE_REGISTRANT},
    )
    session = db_session.scalar(select(PaymentSession).where(PaymentSession.token == token))
    assert session is not None
    merchant_reference = session.merchant_reference
    db_session.expire_all()

    payment = client.post(
        "/api/dev/simulate-paymob-webhook",
        json={"merchant_reference": merchant_reference, "amount": "2500"},
    )
    assert payment.status_code == 200
    data = payment.json()
    assert data["sales_deal_id"] == bitrix.MOCK_SALES_DEAL_BASE + 504
    assert data["b2c_deal_id"] is None

    workflow = db_session.scalar(
        select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 504)
    )
    assert workflow is not None
    assert workflow.sales_deal_id is not None
    assert workflow.b2c_deal_id is None
    assert not workflow.b2c_deal_ids
