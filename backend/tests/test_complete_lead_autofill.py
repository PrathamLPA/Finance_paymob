"""Complete-lead autofill helpers for Bitrix CONVERTED conversion."""

from app.config import Settings
from app.integrations.bitrix import build_complete_lead_autofill_fields


def test_complete_lead_autofill_fills_empty_only_and_copies_i2_due():
    settings = Settings(
        bitrix_field_complete_paid_amount="UF_PAID",
        bitrix_field_complete_student_name="UF_NAME",
        bitrix_field_complete_enrollment_date="UF_ENROLL",
        bitrix_field_complete_schedule_finalized="UF_SCHED",
        bitrix_field_complete_trainer_shared="UF_TRAINER",
        bitrix_field_complete_student_type="UF_STYPE",
        bitrix_field_complete_batch_type="UF_BATCH",
        bitrix_field_complete_ops_notes="UF_NOTES",
        bitrix_complete_schedule_finalized_enum="12912",
        bitrix_complete_trainer_shared_enum="12916",
        bitrix_complete_student_type_enum="13198",
        bitrix_complete_batch_type_enum="13200",
        bitrix_field_installment_2_due_date="UF_CRM_1684374296635",
        bitrix_field_installment_2_due_date_legacy="UF_CRM_1684374142163",
    )
    lead = {
        "TITLE": "Sabith Gmail",
        "OPPORTUNITY": "2.10",
        "UF_NAME": "Already set",  # must not overwrite
        "UF_CRM_1684374142163": "2026-09-30T03:00:00+03:00",
        "UF_CRM_1684374296635": "",
    }
    context = {
        "customer_name": "Abinand",
        "amount_paid": "1.00",
        "total_amount": "2.10",
    }

    fields = build_complete_lead_autofill_fields(settings, lead, context)

    assert fields["UF_PAID"] == "1.00"
    assert "UF_NAME" not in fields  # existing value preserved
    assert fields["UF_SCHED"] == "12912"
    assert fields["UF_TRAINER"] == "12916"
    assert fields["UF_STYPE"] == "13198"
    assert fields["UF_BATCH"] == "13200"
    assert fields["UF_CRM_1684374296635"] == "2026-09-30"
    assert "UF_ENROLL" in fields
    assert "UF_NOTES" in fields


def test_complete_lead_autofill_skips_blank_optional_fields():
    settings = Settings(
        bitrix_field_complete_paid_amount="UF_PAID",
        bitrix_field_complete_credit_card="UF_CC",
        bitrix_field_complete_tenure="UF_TENURE",
        bitrix_field_installment_2_due_date="UF_I2",
        bitrix_field_installment_2_due_date_legacy="UF_I2_LEGACY",
    )
    lead = {"OPPORTUNITY": "100"}
    fields = build_complete_lead_autofill_fields(settings, lead, {"total_amount": "100"})
    assert fields.get("UF_PAID") == "100"
    assert "UF_CC" not in fields
    assert "UF_TENURE" not in fields


def test_mock_attach_lead_payment_proof_if_empty_only_once():
    from app.integrations.bitrix import MockBitrixClient

    client = MockBitrixClient(
        Settings(bitrix_field_complete_payment_proof="UF_PROOF")
    )
    client._mock_leads[42] = {"ID": 42, "UF_PROOF": ""}

    async def _run():
        first = await client.attach_lead_payment_proof_if_empty(
            42, filename="Invoice_1.pdf", content=b"%PDF-1.4"
        )
        second = await client.attach_lead_payment_proof_if_empty(
            42, filename="Invoice_2.pdf", content=b"%PDF-other"
        )
        return first, second

    import asyncio

    first, second = asyncio.run(_run())
    assert first is True
    assert second is False
    assert client._mock_leads[42]["UF_PROOF"][0]["name"] == "Invoice_1.pdf"
