"""Zoho invoice line items should list Bitrix course names when snapshot is present."""

from decimal import Decimal

from app.config import Settings
from app.integrations.zoho import MockZohoBooksClient


def test_line_items_use_course_names_from_pricing_snapshot():
    client = MockZohoBooksClient(Settings(use_mock_integrations=True))
    lines = client._line_items(
        total_amount=Decimal("2.10"),
        currency="AED",
        pricing_lines=[
            {
                "product_name": "ACCA",
                "quantity": "1.00",
                "unit_price": "1.05",
                "line_total": "1.05",
            },
            {
                "product_name": "L5 Principles of Management Consulting",
                "quantity": "1.00",
                "unit_price": "1.05",
                "line_total": "1.05",
            },
        ],
    )
    assert len(lines) == 2
    assert lines[0]["name"] == "ACCA"
    assert lines[0]["rate"] == 1.05
    assert lines[0]["quantity"] == 1.0
    assert lines[1]["name"] == "L5 Principles of Management Consulting"
    assert lines[1]["rate"] == 1.05


def test_line_items_fallback_when_no_courses():
    client = MockZohoBooksClient(Settings(use_mock_integrations=True))
    lines = client._line_items(
        total_amount=Decimal("2.10"),
        currency="AED",
        pricing_lines=None,
    )
    assert len(lines) == 1
    assert lines[0]["name"] == "Course / Training Fee"
    assert lines[0]["rate"] == 2.1


def test_invoice_tax_flags_default_inclusive():
    """Bitrix payable totals must not get another exclusive VAT layer in Zoho."""
    client = MockZohoBooksClient(Settings(use_mock_integrations=True))
    assert client._invoice_tax_flags() == {"is_inclusive_tax": True}


def test_line_items_attach_optional_zoho_tax_id():
    client = MockZohoBooksClient(
        Settings(use_mock_integrations=True, zoho_default_tax_id="tax-123")
    )
    lines = client._line_items(
        total_amount=Decimal("4.20"),
        currency="AED",
        pricing_lines=[{"product_name": "ACCA", "quantity": 1, "line_total": "4.20"}],
    )
    assert lines[0]["tax_id"] == "tax-123"
    assert lines[0]["rate"] == 4.2
