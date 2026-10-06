"""Who collected how much, from recorded cash and POS collections."""

from decimal import Decimal

from app.models.cash_collection import COLLECT_METHOD_CASH, COLLECT_METHOD_POS, STATUS_COLLECTED, CashCollection
from app.models.customer_workflow import CustomerWorkflow
from app.models.staff_user import ROLE_EMPLOYEE, StaffUser
from app.services.cash_collection_service import CashCollectionService
from app.services.staff_auth import hash_password


def test_collection_totals_split_cash_and_pos(db_session):
    ada = StaffUser(
        email="ada@example.com",
        name="Ada",
        password_hash=hash_password("secret1"),
        role=ROLE_EMPLOYEE,
        is_active=True,
    )
    ben = StaffUser(
        email="ben@example.com",
        name="Ben",
        password_hash=hash_password("secret1"),
        role=ROLE_EMPLOYEE,
        is_active=True,
    )
    db_session.add_all([ada, ben])
    db_session.commit()
    workflow = CustomerWorkflow(
        bitrix_lead_id=7001,
        total_amount=Decimal("30.00"),
        amount_paid=Decimal("30.00"),
        currency="AED",
    )
    db_session.add(workflow)
    db_session.commit()

    def add(installment, amount, method, staff_id, customer):
        db_session.add(
            CashCollection(
                workflow_id=workflow.id,
                bitrix_lead_id=7001,
                installment_number=installment,
                customer_name=customer,
                due_amount=amount,
                collected_amount=amount,
                status=STATUS_COLLECTED,
                collected_by_id=staff_id,
                collect_method=method,
            )
        )

    add(1, Decimal("10.00"), COLLECT_METHOD_CASH, ada.id, "Sara")
    add(2, Decimal("4.50"), COLLECT_METHOD_POS, ada.id, "Sara")
    add(3, Decimal("2.00"), COLLECT_METHOD_CASH, ben.id, "Omar")
    db_session.commit()

    rows = {
        row["name"]: row
        for row in CashCollectionService(db_session).collection_totals_by_staff()
    }
    assert rows["Ada"]["cash_collected"] == "10.00"
    assert rows["Ada"]["pos_collected"] == "4.50"
    assert rows["Ada"]["cash_count"] == 1
    assert rows["Ada"]["pos_count"] == 1
    assert rows["Ben"]["cash_collected"] == "2.00"
    assert rows["Ben"]["pos_collected"] == "0.00"
    assert "on_hand" not in rows["Ada"]

    receipts = CashCollectionService(db_session).collection_receipts()
    ada_from = {item["amount"]: item["customer_name"] for item in receipts if item["employee_name"] == "Ada"}
    assert ada_from["10.00"] == "Sara"
    assert ada_from["4.50"] == "Sara"
    assert next(item["customer_name"] for item in receipts if item["employee_name"] == "Ben") == "Omar"

    only_omar = CashCollectionService(db_session).collection_receipts(q="Omar", method="cash")
    assert [item["employee_name"] for item in only_omar] == ["Ben"]
    assert CashCollectionService(db_session).collection_receipts(employee_id=ada.id, method="pos")[0]["amount"] == "4.50"
