"""Course → Handiling Department among B2C - Student Support (no hardcoded SPOCs)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from app.integrations.bitrix import MockBitrixClient
from app.services.b2c_ops_course_assignment import (
    HANDLING_DEPT_FINANCE,
    HANDLING_DEPT_HR,
    HANDLING_DEPT_PROCUREMENT_COMPLIANCE,
    HANDLING_DEPT_PROCUREMENT_SC,
    HANDLING_DEPT_TECH,
    assignees_for_course_units,
    handling_department_for_course,
    pool_for_handling_department,
)


def test_handling_department_for_course_aliases():
    assert handling_department_for_course("CHRP Lab") == HANDLING_DEPT_HR
    assert handling_department_for_course("CMA Part 1") == HANDLING_DEPT_FINANCE
    assert handling_department_for_course("CIPS Level 4") == HANDLING_DEPT_PROCUREMENT_SC
    assert handling_department_for_course("CSCP") == HANDLING_DEPT_PROCUREMENT_COMPLIANCE
    assert handling_department_for_course("EV Engineering") == HANDLING_DEPT_TECH
    assert handling_department_for_course("EV") == HANDLING_DEPT_PROCUREMENT_COMPLIANCE
    assert handling_department_for_course("CTM Advanced") == HANDLING_DEPT_TECH
    assert handling_department_for_course("CT") == HANDLING_DEPT_HR
    assert handling_department_for_course("Power BI Desktop") == HANDLING_DEPT_TECH
    assert handling_department_for_course("Unknown XYZ") is None


def test_cipd_maps_to_hr_people_development_when_enum_configured():
    from app.config import get_settings

    settings = get_settings()
    settings.bitrix_handling_dept_hr_people_development_enum = "19722"
    assert (
        handling_department_for_course("CIPD Level 3", settings=settings) == 19722
    )
    assert (
        handling_department_for_course(
            "CIPD Level 5 - Associate Diploma in Organisational Learning and Development Course",
            settings=settings,
        )
        == 19722
    )
    assert handling_department_for_course("CIPD Courses", settings=settings) == 19722
    # Without enum configured, CIPD must not fall through to another dept.
    settings.bitrix_handling_dept_hr_people_development_enum = ""
    assert handling_department_for_course("CIPD Level 3", settings=settings) is None


def test_pool_only_from_b2c_student_support_with_matching_handling():
    bitrix = MockBitrixClient()
    bitrix.settings.bitrix_b2c_ops_department_id = "108"
    bitrix.seed_department(108, name="B2C - Student Support")
    # In B2C - Student Support with Finance handling
    bitrix.seed_user(
        201,
        email="fin1@test.com",
        name="Finance One",
        department_ids=[108],
        handling_department_enum_id=HANDLING_DEPT_FINANCE,
    )
    bitrix.seed_user(
        202,
        email="fin2@test.com",
        name="Finance Two",
        department_ids=[108],
        handling_department_enum_id=HANDLING_DEPT_FINANCE,
    )
    # Same handling dept but NOT in B2C - Student Support — must be ignored
    bitrix.seed_user(
        999,
        email="outsider@test.com",
        name="Outsider",
        department_ids=[14],
        handling_department_enum_id=HANDLING_DEPT_FINANCE,
    )
    # In B2C but different handling
    bitrix.seed_user(
        301,
        email="hr@test.com",
        name="HR Person",
        department_ids=[108],
        handling_department_enum_id=HANDLING_DEPT_HR,
    )

    employees = asyncio.run(bitrix.list_b2c_ops_employees())
    assert {e["id"] for e in employees} == {201, 202, 301}
    pool = pool_for_handling_department(employees, HANDLING_DEPT_FINANCE)
    assert pool == [201, 202]
    assert 999 not in pool


def test_b2c_ops_cards_assigned_from_department_by_handling(db_session):
    from app.db.session import Base
    from app.models import assignment_cursor as _ac  # noqa: F401

    Base.metadata.create_all(bind=db_session.get_bind())

    bitrix = MockBitrixClient()
    bitrix.settings.bitrix_b2c_pipeline_id = "42"
    bitrix.settings.bitrix_b2c_ops_department_id = "108"
    bitrix.settings.bitrix_b2c_ops_assign_by_course_handling_dept = True
    bitrix.seed_department(108, name="B2C - Student Support")
    bitrix.seed_user(
        501,
        email="ziya-pool@test.com",
        name="Ops Finance",
        department_ids=[108],
        handling_department_enum_id=HANDLING_DEPT_FINANCE,
    )
    bitrix.seed_user(
        502,
        email="ramya-pool@test.com",
        name="Ops HR",
        department_ids=[108],
        handling_department_enum_id=HANDLING_DEPT_HR,
    )
    bitrix.seed_user(
        503,
        email="yaseen-pool@test.com",
        name="Ops Tech",
        department_ids=[108],
        handling_department_enum_id=HANDLING_DEPT_TECH,
    )
    # Hardcoded-style outsider must not win assignment
    bitrix.seed_user(
        163568,
        email="ziya-outside@test.com",
        name="Outside Ziya",
        department_ids=[286],
        handling_department_enum_id=HANDLING_DEPT_FINANCE,
    )

    bitrix.seed_lead(802, email="c@test.com", name="Customer", amount=Decimal("9000"))
    bitrix.seed_lead_products(
        802,
        [
            {"productId": 1, "productName": "CMA", "price": "3000", "quantity": 1},
            {"productId": 2, "productName": "CHRP", "price": "3000", "quantity": 1},
            {
                "productId": 3,
                "productName": "Power BI",
                "price": "3000",
                "quantity": 1,
            },
        ],
    )
    sales_id = asyncio.run(bitrix.convert_lead_to_sales_deal(802, {}))
    assignees = asyncio.run(
        assignees_for_course_units(
            bitrix, ["CMA", "CHRP", "Power BI"], db=db_session
        )
    )
    assert assignees == [501, 502, 503]
    ids = asyncio.run(
        bitrix.create_b2c_ops_deals_from_sales(
            sales_deal_id=sales_id,
            lead_id=802,
            context={},
            assignee_user_ids=assignees,
        )
    )
    assert len(ids) == 3
    assigned = [bitrix._mock_deals[i]["ASSIGNED_BY_ID"] for i in ids]
    assert assigned == [501, 502, 503]
