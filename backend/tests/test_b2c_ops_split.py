"""B2C Ops cards: one deal per Course (+ Lab / Study Material via Associated course)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from app.integrations.bitrix import (
    CATALOG_ASSOCIATED_IDS_KEY,
    CATALOG_PRODUCT_KIND_KEY,
    MockBitrixClient,
    PRODUCT_KIND_COURSE,
    PRODUCT_KIND_LAB,
    PRODUCT_KIND_STUDY,
    PRODUCT_KIND_UNSET,
    _product_row_name,
    bitrix_download_is_login_html,
    bitrix_file_url_with_auth,
    bitrix_webhook_auth_token,
    crm_show_file_ref,
    uf_code_to_item_field,
    url_machine_for_file,
    classify_product_kind,
    expand_course_bundle_units,
    expand_product_units,
    group_course_product_bundles,
    parse_associated_product_ids,
    parse_product_type_enum_id,
    prefer_parent_catalog_fields,
)
from app.integrations.factory import get_bitrix_client
from app.models.customer_workflow import CustomerWorkflow
from tests.conftest import SAMPLE_REGISTRANT


def test_catalog_offer_lab_joins_course_sku_on_the_deal():
    """SKU rows fail crm.product.get; type and associated course are on the parent."""
    course = prefer_parent_catalog_fields(
        {"id": 12538, "type": 4, "parentId": {"value": "12536"}},
        {"id": 12536, "type": 3, "property400": {"value": "494", "valueEnum": "Course"}},
        "PROPERTY_400",
        "PROPERTY_414",
    )
    lab = prefer_parent_catalog_fields(
        {"id": 12542, "type": 4, "parentId": {"value": "12540"}},
        {
            "id": 12540,
            "type": 3,
            "property400": {"value": "496", "valueEnum": "Lab"},
            "property414": [{"value": "12538"}, {"value": "2306"}],
        },
        "PROPERTY_400",
        "PROPERTY_414",
    )
    rows = [
        {
            "productId": 12538,
            "productName": "test",
            "quantity": 1,
            CATALOG_PRODUCT_KIND_KEY: classify_product_kind(
                parse_product_type_enum_id(course.get("PROPERTY_400"))
            ),
            CATALOG_ASSOCIATED_IDS_KEY: parse_associated_product_ids(
                course.get("PROPERTY_414")
            ),
        },
        {
            "productId": 12542,
            "productName": "test Lab",
            "quantity": 1,
            CATALOG_PRODUCT_KIND_KEY: classify_product_kind(
                parse_product_type_enum_id(lab.get("PROPERTY_400"))
            ),
            CATALOG_ASSOCIATED_IDS_KEY: parse_associated_product_ids(
                lab.get("PROPERTY_414")
            ),
        },
    ]
    bundles = group_course_product_bundles(rows)
    assert len(bundles) == 1
    assert bundles[0]["title"] == "test"
    assert {row["productId"] for row in bundles[0]["products"]} == {12538, 12542}


def test_crm_show_file_uses_item_machine_url():
    ref = crm_show_file_ref(
        "/bitrix/components/bitrix/crm.deal.show/show_file.php"
        "?auth=&ownerId=155062&fieldName=UF_CRM_69D39E301706D&fileId=8409606"
    )
    assert ref is not None
    assert ref["entity_type_id"] == 2
    assert ref["owner_id"] == 155062
    assert uf_code_to_item_field(ref["field_name"]) == "ufCrm_69D39E301706D"
    machine = url_machine_for_file(
        {"id": 8409606, "urlMachine": "https://example.test/file"},
        8409606,
    )
    assert machine == "https://example.test/file"


def test_crm_file_download_rejects_login_html_and_adds_webhook_auth():
    webhook = "https://learnerspoint.bitrix24.com/rest/161836/webhook-token/"
    assert bitrix_webhook_auth_token(webhook) == "webhook-token"
    url = (
        "/bitrix/components/bitrix/crm.deal.show/show_file.php"
        "?fileId=8408920&ownerTypeId=2&ownerId=154988&auth="
    )
    authed = bitrix_file_url_with_auth(url, bitrix_webhook_auth_token(webhook))
    assert "auth=webhook-token" in authed
    assert bitrix_download_is_login_html(b"<!DOCTYPE html><html>login</html>", "")
    assert not bitrix_download_is_login_html(b"%PDF-1.4", "application/pdf")


def test_parse_product_type_and_associated_ids():
    assert parse_product_type_enum_id({"value": "496"}) == "496"
    assert parse_product_type_enum_id("494") == "494"
    assert parse_associated_product_ids([10, "20", {"value": 30}]) == [10, 20, 30]
    assert classify_product_kind("494") == PRODUCT_KIND_COURSE
    assert classify_product_kind("496") == PRODUCT_KIND_LAB
    assert classify_product_kind("498") == PRODUCT_KIND_STUDY
    assert classify_product_kind(None) == PRODUCT_KIND_UNSET


def test_group_by_product_type_and_associated_course():
    """Course + Lab/Study Material linked via Associated course → one Ops card."""
    rows = [
        {
            "productId": 11,
            "productName": "CHRP",
            "price": "1000",
            "quantity": 1,
            CATALOG_PRODUCT_KIND_KEY: PRODUCT_KIND_COURSE,
            CATALOG_ASSOCIATED_IDS_KEY: [12, 14],
        },
        {
            "productId": 12,
            "productName": "CHRP Lab",
            "price": "200",
            "quantity": 1,
            CATALOG_PRODUCT_KIND_KEY: PRODUCT_KIND_LAB,
            CATALOG_ASSOCIATED_IDS_KEY: [11],
        },
        {
            "productId": 14,
            "productName": "CHRP study materials",
            "price": "50",
            "quantity": 1,
            CATALOG_PRODUCT_KIND_KEY: PRODUCT_KIND_STUDY,
            CATALOG_ASSOCIATED_IDS_KEY: [11],
        },
        {
            "productId": 22,
            "productName": "Course B",
            "price": "2000",
            "quantity": 2,
            CATALOG_PRODUCT_KIND_KEY: PRODUCT_KIND_COURSE,
            CATALOG_ASSOCIATED_IDS_KEY: [],
        },
    ]
    bundles = group_course_product_bundles(rows)
    assert len(bundles) == 2
    chrp = next(b for b in bundles if b["title"] == "CHRP")
    assert len(chrp["products"]) == 3
    assert chrp["quantity"] == 1
    course_b = next(b for b in bundles if b["title"] == "Course B")
    assert course_b["quantity"] == 2
    units = expand_course_bundle_units(rows)
    assert len(units) == 3  # CHRP x1 + Course B x2


def test_unset_product_type_is_course_anchor():
    rows = [
        {
            "productId": 1,
            "productName": "ACCA",
            "price": "4.20",
            "quantity": 1,
            CATALOG_PRODUCT_KIND_KEY: PRODUCT_KIND_UNSET,
            CATALOG_ASSOCIATED_IDS_KEY: [],
        }
    ]
    bundles = group_course_product_bundles(rows)
    assert len(bundles) == 1
    assert bundles[0]["title"] == "ACCA"


def test_lab_without_associated_course_is_own_card():
    rows = [
        {
            "productId": 99,
            "productName": "Orphan Lab",
            "price": "100",
            "quantity": 1,
            CATALOG_PRODUCT_KIND_KEY: PRODUCT_KIND_LAB,
            CATALOG_ASSOCIATED_IDS_KEY: [],
        }
    ]
    bundles = group_course_product_bundles(rows)
    assert len(bundles) == 1
    assert bundles[0]["title"] == "Orphan Lab"


def test_lab_linked_to_multiple_courses_appears_on_each_card():
    """One Lab can list several Associated courses → copy onto each matching Ops card."""
    rows = [
        {
            "productId": 11,
            "productName": "Course A",
            "price": "1000",
            "quantity": 1,
            CATALOG_PRODUCT_KIND_KEY: PRODUCT_KIND_COURSE,
            CATALOG_ASSOCIATED_IDS_KEY: [],
        },
        {
            "productId": 22,
            "productName": "Course B",
            "price": "2000",
            "quantity": 1,
            CATALOG_PRODUCT_KIND_KEY: PRODUCT_KIND_COURSE,
            CATALOG_ASSOCIATED_IDS_KEY: [],
        },
        {
            "productId": 33,
            "productName": "Shared Lab",
            "price": "100",
            "quantity": 1,
            CATALOG_PRODUCT_KIND_KEY: PRODUCT_KIND_LAB,
            CATALOG_ASSOCIATED_IDS_KEY: [11, 22],
        },
    ]
    bundles = group_course_product_bundles(rows)
    assert len(bundles) == 2
    for title in ("Course A", "Course B"):
        bundle = next(b for b in bundles if b["title"] == title)
        names = {_product_row_name(p) for p in bundle["products"]}
        assert "Shared Lab" in names
        assert title in names


def test_lab_assoc_not_on_deal_becomes_separate_card():
    """Lab associated to a course that was not purchased → own Ops card."""
    rows = [
        {
            "productId": 11,
            "productName": "Bought Course",
            "price": "1000",
            "quantity": 1,
            CATALOG_PRODUCT_KIND_KEY: PRODUCT_KIND_COURSE,
            CATALOG_ASSOCIATED_IDS_KEY: [],
        },
        {
            "productId": 99,
            "productName": "Lab For Other Course",
            "price": "100",
            "quantity": 1,
            CATALOG_PRODUCT_KIND_KEY: PRODUCT_KIND_LAB,
            CATALOG_ASSOCIATED_IDS_KEY: [55],  # not on deal
        },
    ]
    bundles = group_course_product_bundles(rows)
    assert len(bundles) == 2
    titles = {b["title"] for b in bundles}
    assert titles == {"Bought Course", "Lab For Other Course"}


def test_expand_product_units_by_quantity():
    rows = [
        {"productId": 1, "productName": "A", "price": "100", "quantity": 1},
        {"productId": 2, "PRODUCT_NAME": "B", "PRICE": "200", "QUANTITY": 2},
    ]
    units = expand_product_units(rows)
    assert len(units) == 3
    assert all(u.get("quantity") == 1 or u.get("QUANTITY") == 1 for u in units)
    names = [u.get("productName") or u.get("PRODUCT_NAME") for u in units]
    assert names.count("A") == 1
    assert names.count("B") == 2


def test_create_b2c_ops_deals_groups_via_catalog_properties():
    bitrix = MockBitrixClient()
    bitrix.settings.bitrix_b2c_pipeline_id = "42"
    bitrix.settings.bitrix_field_original_deal_id = "UF_CRM_ORIGINAL_DEAL_ID"
    bitrix.seed_lead(501, email="ops@test.com", name="Ops Student", amount=Decimal("5000"))
    bitrix.seed_catalog_product(
        11, name="CHRP", price=Decimal("1000"), product_type_enum="494", associated_course_ids=[12, 14]
    )
    bitrix.seed_catalog_product(
        12, name="CHRP Lab", price=Decimal("200"), product_type_enum="496", associated_course_ids=[11]
    )
    bitrix.seed_catalog_product(
        14,
        name="CHRP study materials",
        price=Decimal("50"),
        product_type_enum="498",
        associated_course_ids=[11],
    )
    bitrix.seed_catalog_product(
        22, name="Course B", price=Decimal("2000"), product_type_enum="494"
    )
    bitrix.seed_lead_products(
        501,
        [
            {"productId": 11, "productName": "CHRP", "price": "1000", "quantity": 1},
            {"productId": 12, "productName": "CHRP Lab", "price": "200", "quantity": 1},
            {
                "productId": 14,
                "productName": "CHRP study materials",
                "price": "50",
                "quantity": 1,
            },
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
    # CHRP bundle = 1 card; Course B qty 2 = 2 cards → 3 total
    assert len(ids) == 3
    chrp_deal = None
    for deal_id in ids:
        deal = bitrix._mock_deals[deal_id]
        assert str(deal.get("CATEGORY_ID")) == "42"
        assert deal.get("LEAD_ID") == 501
        assert deal.get("UF_CRM_ORIGINAL_DEAL_ID") == sales_id
        rows = bitrix._mock_product_rows.get(("D", deal_id), [])
        names = [r.get("productName") or r.get("PRODUCT_NAME") for r in rows]
        if any(n == "CHRP" for n in names):
            chrp_deal = deal_id
            assert len(rows) == 3
            assert set(names) == {"CHRP", "CHRP Lab", "CHRP study materials"}
            assert deal["OPPORTUNITY"] == "1250.00"
        else:
            assert len(rows) == 1
            assert names == ["Course B"]
    assert chrp_deal is not None
    titles = [bitrix._mock_deals[i]["TITLE"] for i in ids]
    assert sum("Course B" in t for t in titles) == 2


def test_create_b2c_ops_skipped_without_pipeline():
    bitrix = MockBitrixClient()
    bitrix.settings.bitrix_b2c_pipeline_id = ""
    bitrix.seed_lead(502, email="a@b.com", name="A", amount=Decimal("100"))
    sales_id = asyncio.run(bitrix.convert_lead_to_sales_deal(502, {}))
    ids = asyncio.run(
        bitrix.create_b2c_ops_deals_from_sales(
            sales_deal_id=sales_id, lead_id=502, context={}
        )
    )
    assert ids == []


def test_first_payment_creates_b2c_ops_per_bundle(client, seed_lead, db_session):
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
    bitrix.seed_catalog_product(
        1, name="Python", price=Decimal("4000"), product_type_enum="494", associated_course_ids=[2]
    )
    bitrix.seed_catalog_product(
        2,
        name="Python Lab",
        price=Decimal("500"),
        product_type_enum="496",
        associated_course_ids=[1],
    )
    bitrix.seed_catalog_product(
        3, name="Excel", price=Decimal("3000"), product_type_enum="494"
    )
    bitrix.seed_lead_products(
        503,
        [
            {"productId": 1, "productName": "Python", "price": "4000", "quantity": 1},
            {"productId": 2, "productName": "Python Lab", "price": "500", "quantity": 1},
            {"productId": 3, "productName": "Excel", "price": "3000", "quantity": 2},
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
    # Python+Lab = 1; Excel qty 2 = 2 → 3 Ops cards
    assert len(workflow.b2c_deal_ids) == 3
    assert workflow.b2c_deal_id == workflow.b2c_deal_ids[0]

    python_deal = None
    for deal_id in workflow.b2c_deal_ids:
        rows = bitrix._mock_product_rows.get(("D", int(deal_id)), [])
        names = [r.get("productName") for r in rows]
        if "Python" in names:
            python_deal = deal_id
            assert set(names) == {"Python", "Python Lab"}
    assert python_deal is not None

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
