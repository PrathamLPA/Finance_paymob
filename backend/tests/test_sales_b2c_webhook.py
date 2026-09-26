"""Bitrix-owned Lead→Sales: Sales outbound webhook creates B2C Ops cards."""

from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.integrations.factory import get_bitrix_client
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import PaymentSession
from tests.conftest import SAMPLE_REGISTRANT


def test_sales_pipeline_webhook_splits_b2c_when_convert_disabled(
    client, seed_lead, db_session, monkeypatch
):
    monkeypatch.setenv("BITRIX_BACKEND_CONVERT_LEAD_TO_SALES", "false")
    monkeypatch.setenv("BITRIX_BACKEND_B2C_OPS_SPLIT", "true")
    monkeypatch.setenv("BITRIX_B2C_PIPELINE_ID", "99")
    monkeypatch.setenv("BITRIX_SALES_PIPELINE_ID", "16")
    monkeypatch.setenv("BITRIX_SALES_B2C_SPLIT_STAGE_ID", "")
    get_settings.cache_clear()

    settings = get_settings()
    bitrix = get_bitrix_client()
    bitrix.settings.bitrix_backend_convert_lead_to_sales = False
    bitrix.settings.bitrix_backend_b2c_ops_split = True
    bitrix.settings.bitrix_b2c_pipeline_id = "99"
    bitrix.settings.bitrix_sales_pipeline_id = "16"
    bitrix.settings.bitrix_sales_b2c_split_stage_id = ""

    lead_id = 920001
    seed_lead(lead_id, email="sales-b2c@test.com", amount=Decimal("5000"))
    bitrix.seed_catalog_product(
        71, name="Python", price=Decimal("3000"), product_type_enum="494"
    )
    bitrix.seed_catalog_product(
        72, name="Excel", price=Decimal("2000"), product_type_enum="494"
    )
    bitrix.seed_lead_products(
        lead_id,
        [
            {"productId": 71, "productName": "Python", "price": "3000", "quantity": 1},
            {"productId": 72, "productName": "Excel", "price": "2000", "quantity": 1},
        ],
    )

    link = client.post(
        "/api/dev/send-payment-link",
        json={
            "lead_id": lead_id,
            "customer_email": "sales-b2c@test.com",
            "total_amount": "5000",
        },
    )
    token = link.json()["token"]
    client.post(
        f"/api/payment/{token}/accept",
        json={"accepted": True, **SAMPLE_REGISTRANT},
    )
    session = db_session.scalar(select(PaymentSession).where(PaymentSession.token == token))
    assert session is not None
    db_session.expire_all()

    payment = client.post(
        "/api/dev/simulate-paymob-webhook",
        json={"merchant_reference": session.merchant_reference, "amount": "2500"},
    )
    assert payment.status_code == 200
    data = payment.json()
    # Backend convert off — no Sales/B2C from payment webhook.
    assert data.get("sales_deal_id") in (None, 0) or data["status"] == "ok"
    workflow = db_session.scalar(
        select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == lead_id)
    )
    assert workflow is not None
    assert workflow.amount_paid == Decimal("2500.00")
    assert workflow.b2c_deal_id is None

    # Bitrix creates Sales (simulate robot), then outbound hits us.
    sales_id = 700001
    bitrix._mock_deals[sales_id] = {
        "ID": sales_id,
        "LEAD_ID": lead_id,
        "TITLE": f"Sales - lead {lead_id}",
        "CATEGORY_ID": "16",
        "STAGE_ID": "C16:NEW",
        "OPPORTUNITY": "5000",
        "CURRENCY_ID": "AED",
        "ASSIGNED_BY_ID": 1,
    }
    bitrix._mock_product_rows[("D", sales_id)] = [
        {"productId": 71, "productName": "Python", "price": "3000", "quantity": 1},
        {"productId": 72, "productName": "Excel", "price": "2000", "quantity": 1},
    ]

    resp = client.post(
        "/webhooks/bitrix24",
        data={
            "event": "ONCRMDEALUPDATE",
            "data[FIELDS][ID]": str(sales_id),
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "processed"
    assert body["source"] == "sales_b2c_ops_split"
    assert len(body["b2c_deal_ids"]) == 2

    db_session.refresh(workflow)
    assert workflow.sales_deal_id == sales_id
    assert workflow.finance_deal_id != sales_id
    assert workflow.b2c_deal_ids is not None
    assert len(workflow.b2c_deal_ids) == 2

    # Idempotent second hit.
    again = client.post(
        "/webhooks/bitrix24",
        data={
            "event": "ONCRMDEALUPDATE",
            "data[FIELDS][ID]": str(sales_id),
        },
    )
    assert again.status_code == 200
    assert again.json()["status"] == "ignored"
    assert again.json()["reason"] == "b2c_already_split"

    get_settings.cache_clear()
