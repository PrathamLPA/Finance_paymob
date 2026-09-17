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
        bitrix_field_complete_paid_status="UF_PAID_STATUS",
        bitrix_complete_paid_status_fully_paid_enum="19692",
        bitrix_complete_paid_status_partially_paid_enum="19694",
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
    assert fields["UF_PAID_STATUS"] == "19694"
    assert "UF_NAME" not in fields  # existing value preserved
    assert fields["UF_SCHED"] == "12912"
    assert fields["UF_TRAINER"] == "12916"
    assert fields["UF_STYPE"] == "13198"
    assert fields["UF_BATCH"] == "13200"
    assert fields["UF_CRM_1684374296635"] == "2026-09-30"
    assert "UF_ENROLL" in fields
    assert "UF_NOTES" in fields


def test_complete_lead_autofill_fills_payment_section_and_comments():
    settings = Settings(
        bitrix_field_complete_paid_amount="UF_PAID",
        bitrix_field_complete_student_name="UF_NAME",
        bitrix_field_total_amount="UF_TOTAL",
        bitrix_field_installment_1="UF_I1",
        bitrix_field_installment_1_date="UF_I1_DATE",
        bitrix_field_installment_2_due_date="UF_CRM_1684374296635",
        bitrix_field_installment_2_due_date_legacy="UF_CRM_1684374142163",
        bitrix_complete_required_string_fields="UF_DESIGNATION,UF_DURATION",
        bitrix_complete_required_placeholder="To be confirmed by Ops",
    )
    lead = {
        "TITLE": "Sabith",
        "OPPORTUNITY": "",
        "COMMENTS": "",
        "UF_CRM_1684374142163": "2026-09-30T03:00:00+03:00",
        "UF_DESIGNATION": "",
    }
    fields = build_complete_lead_autofill_fields(
        settings,
        lead,
        {
            "customer_name": "Abinand",
            "amount_paid": "1.00",
            "total_amount": "2.10",
            "currency": "AED",
            "course_title": "CMA",
        },
    )
    assert fields["UF_PAID"] == "1.00"
    assert fields["UF_TOTAL"] == "2.10|AED"
    assert fields["UF_I1"] == "1.00|AED"
    assert fields["UF_CRM_1684374296635"] == "2026-09-30"
    assert "CMA" in fields["COMMENTS"]
    assert fields["UF_DESIGNATION"] == "To be confirmed by Ops"
    assert fields["UF_DURATION"] == "To be confirmed by Ops"
    assert fields["OPPORTUNITY"] == "2.10"


def test_complete_lead_autofill_marks_fully_paid_when_first_payment_covers_total():
    settings = Settings(
        bitrix_field_complete_paid_amount="UF_PAID",
        bitrix_field_complete_paid_status="UF_PAID_STATUS",
        bitrix_complete_paid_status_fully_paid_enum="19692",
        bitrix_complete_paid_status_partially_paid_enum="19694",
    )

    fields = build_complete_lead_autofill_fields(
        settings,
        {"OPPORTUNITY": "100.00"},
        {"amount_paid": "100.00", "total_amount": "100.00"},
    )

    assert fields["UF_PAID_STATUS"] == "19692"


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


def test_mock_attach_lead_invoice_file_if_empty():
    from app.integrations.bitrix import MockBitrixClient

    client = MockBitrixClient(
        Settings(bitrix_field_lead_invoice_file="UF_INVOICE")
    )
    client._mock_leads[43] = {"ID": 43, "UF_INVOICE": []}

    async def _run():
        first = await client.attach_lead_invoice_file_if_empty(
            43, filename="Invoice_INV.pdf", content=b"%PDF-1.4"
        )
        second = await client.attach_lead_invoice_file_if_empty(
            43, filename="Other.pdf", content=b"%PDF-other"
        )
        return first, second

    import asyncio

    first, second = asyncio.run(_run())
    assert first is True
    assert second is False
    assert client._mock_leads[43]["UF_INVOICE"][0]["name"] == "Invoice_INV.pdf"


def test_real_bitrix_file_uf_uses_filedata_payload():
    """Regression: [[name, b64]] is accepted by Bitrix but stores nothing."""
    import asyncio
    import base64

    from app.integrations.bitrix import RealBitrixClient

    captured: dict = {}

    class Stub(RealBitrixClient):
        async def get_lead(self, lead_id: int) -> dict:
            if captured.get("updated"):
                # Simulate successful store after update.
                return {
                    "ID": lead_id,
                    "UF_PROOF": {
                        "id": 1,
                        "showUrl": "/x",
                        "downloadUrl": "/y",
                    },
                }
            return {"ID": lead_id, "UF_PROOF": None}

        async def _call(self, method: str, params: dict | None = None) -> dict:
            captured["method"] = method
            captured["params"] = params
            captured["updated"] = True
            return {"result": True}

    client = Stub(Settings(bitrix_field_complete_payment_proof="UF_PROOF"))
    ok = asyncio.run(
        client.attach_lead_payment_proof_if_empty(
            99, filename="Invoice_X.pdf", content=b"%PDF-1.4"
        )
    )
    assert ok is True
    assert captured["method"] == "crm.lead.update"
    value = captured["params"]["fields"]["UF_PROOF"]
    assert isinstance(value, dict)
    assert "fileData" in value
    name, b64 = value["fileData"]
    assert name == "Invoice_X.pdf"
    assert base64.b64decode(b64) == b"%PDF-1.4"


def test_real_bitrix_invoice_trigger_returns_false_when_bitrix_does_not_activate():
    import asyncio

    from app.integrations.bitrix import RealBitrixClient

    class Stub(RealBitrixClient):
        async def get_lead(self, lead_id: int) -> dict:
            return {"ID": lead_id, "STATUS_ID": "10"}

        async def _call(self, method: str, params: dict | None = None) -> dict:
            assert method == "crm.automation.trigger"
            assert params == {"target": "LEAD_99", "code": "7tmq9"}
            return {"result": False}

    client = Stub(
        Settings(
            bitrix_invoice_sent_trigger_url=(
                "https://example.bitrix24.com/rest/x/crm.automation.trigger/"
                "?target=LEAD_{{ID}}&code=7tmq9"
            )
        )
    )

    assert asyncio.run(client.trigger_invoice_sent(99)) is False


def test_real_bitrix_invoice_trigger_logs_verified_stage_change():
    import asyncio

    from app.integrations.bitrix import RealBitrixClient

    class Stub(RealBitrixClient):
        activated = False

        async def get_lead(self, lead_id: int) -> dict:
            return {
                "ID": lead_id,
                "STATUS_ID": "CONVERTED" if self.activated else "10",
            }

        async def _call(self, method: str, params: dict | None = None) -> dict:
            self.activated = True
            return {"result": True}

    client = Stub(
        Settings(
            bitrix_invoice_sent_trigger_url=(
                "https://example.bitrix24.com/rest/x/crm.automation.trigger/"
                "?target=LEAD_{{ID}}&code=7tmq9"
            )
        )
    )

    assert asyncio.run(client.trigger_invoice_sent(99)) is True


def test_build_deal_payment_fields_copies_lead_and_fills_context_gaps():
    from app.integrations.bitrix import build_deal_payment_fields_from_lead

    settings = Settings(
        bitrix_field_lead_total_amount="UF_TOTAL_",
        bitrix_field_total_amount="UF_TOTAL",
        bitrix_field_amount_paid="UF_PAID",
        bitrix_field_installment_1="UF_I1",
        bitrix_field_installment_2="UF_I2",
        bitrix_field_installment_2_due_date="UF_I2_DUE",
    )
    lead = {
        "OPPORTUNITY": "2.10",
        "CURRENCY_ID": "AED",
        "UF_I1": "1.00|AED",
        "UF_I2": "1.10|AED",
        "UF_I2_DUE": "2026-10-01",
    }
    fields = build_deal_payment_fields_from_lead(
        settings,
        lead,
        {"amount_paid": "1.00", "total_amount": "2.10", "remaining_balance": "1.10"},
    )
    assert fields["UF_I1"] == "1.00|AED"
    assert fields["UF_I2"] == "1.10|AED"
    assert fields["UF_I2_DUE"] == "2026-10-01"
    assert fields["UF_PAID"] == "1.00"
    assert fields["UF_TOTAL_"] == "2.10|AED" or fields["UF_TOTAL"] == "2.10|AED"
    assert fields["OPPORTUNITY"] == "2.10"
