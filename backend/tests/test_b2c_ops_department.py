"""Fetch B2C Ops employees from Bitrix department + round-robin assign."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from app.integrations.bitrix import MockBitrixClient
from app.models.assignment_cursor import B2C_OPS_CURSOR_KEY, claim_round_robin_ids


def test_list_b2c_ops_employees_by_department_name():
    bitrix = MockBitrixClient()
    bitrix.settings.bitrix_b2c_ops_department_name = "B2C - Student Support"
    bitrix.settings.bitrix_b2c_ops_department_id = ""
    bitrix.seed_department(55, name="B2C - Student Support")
    bitrix.seed_user(
        501, email="ops1@test.com", name="Ops One", department_ids=[55]
    )
    bitrix.seed_user(
        502, email="ops2@test.com", name="Ops Two", department_ids=[55]
    )
    bitrix.seed_user(
        503, email="sales@test.com", name="Sales Only", department_ids=[1]
    )

    employees = asyncio.run(bitrix.list_b2c_ops_employees())
    ids = [e["id"] for e in employees]
    assert ids == [501, 502]
    assert employees[0]["email"] == "ops1@test.com"


def test_claim_round_robin_ids(db_session):
    # Ensure model table exists for this session's metadata.
    from app.models import assignment_cursor as _ac  # noqa: F401
    from app.db.session import Base

    Base.metadata.create_all(bind=db_session.get_bind())

    first = claim_round_robin_ids(
        db_session, key=B2C_OPS_CURSOR_KEY, pool=[10, 20, 30], count=2
    )
    assert first == [10, 20]
    second = claim_round_robin_ids(
        db_session, key=B2C_OPS_CURSOR_KEY, pool=[10, 20, 30], count=2
    )
    assert second == [30, 10]


def test_b2c_ops_cards_assigned_round_robin_from_department(db_session):
    from app.db.session import Base
    from app.models import assignment_cursor as _ac  # noqa: F401

    Base.metadata.create_all(bind=db_session.get_bind())

    bitrix = MockBitrixClient()
    bitrix.settings.bitrix_b2c_pipeline_id = "42"
    bitrix.settings.bitrix_b2c_ops_department_name = "B2C - Student Support"
    bitrix.settings.bitrix_b2c_ops_assign_from_department = True
    bitrix.seed_department(55, name="B2C - Student Support")
    bitrix.seed_user(601, email="a@test.com", name="A", department_ids=[55])
    bitrix.seed_user(602, email="b@test.com", name="B", department_ids=[55])
    bitrix.seed_lead(701, email="c@test.com", name="Customer", amount=Decimal("3000"))
    bitrix.seed_lead_products(
        701,
        [
            {"productId": 1, "productName": "C1", "price": "1000", "quantity": 1},
            {"productId": 2, "productName": "C2", "price": "1000", "quantity": 2},
        ],
    )
    sales_id = asyncio.run(bitrix.convert_lead_to_sales_deal(701, {}))
    employees = asyncio.run(bitrix.list_b2c_ops_employees())
    pool = [int(e["id"]) for e in employees]
    assignees = claim_round_robin_ids(
        db_session, key=B2C_OPS_CURSOR_KEY, pool=pool, count=3
    )
    ids = asyncio.run(
        bitrix.create_b2c_ops_deals_from_sales(
            sales_deal_id=sales_id,
            lead_id=701,
            context={},
            assignee_user_ids=assignees,
        )
    )
    assert len(ids) == 3
    assigned = [bitrix._mock_deals[i]["ASSIGNED_BY_ID"] for i in ids]
    assert assigned == [601, 602, 601]
