"""Complete-lead autofill helpers for Bitrix CONVERTED conversion."""

from app.config import Settings
from app.integrations.bitrix import build_complete_lead_autofill_fields


def test_complete_lead_autofill_writes_student_mail_and_contact():
    settings = Settings(
        bitrix_field_complete_student_name="UF_NAME",
        bitrix_field_student_mail="UF_MAIL",
        bitrix_field_student_contact="UF_PHONE",
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
    )
    fields = build_complete_lead_autofill_fields(
        settings,
        {"TITLE": "Lead"},
        {
            "customer_name": "Sara Khan",
            "student_email": "sara@test.com",
            "student_phone": "+971500000001",
            "amount_paid": "1.00",
            "total_amount": "2.10",
        },
    )
    assert fields["UF_NAME"] == "Sara Khan"
    assert fields["UF_MAIL"] == "sara@test.com"
    assert fields["UF_PHONE"] == "+971500000001"


def test_resolve_student_identity_someone_else_uses_candidate():
    from app.services.terms_service import TermsService

    name, email, phone = TermsService._resolve_student_identity(
        course_for="someone_else",
        registrant_name="Payer",
        registrant_email="payer@test.com",
        registrant_phone="+971511111111",
        participants=[{"name": "Sara", "email": "sara@test.com"}],
    )
    assert name == "Sara"
    assert email == "sara@test.com"
    assert phone is None

    name, email, phone = TermsService._resolve_student_identity(
        course_for="self",
        registrant_name="Payer",
        registrant_email="payer@test.com",
        registrant_phone="+971511111111",
        participants=[],
    )
    assert name == "Payer"
    assert email == "payer@test.com"
    assert phone == "+971511111111"


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
        bitrix_field_installment_2_due_date_legacy="",
        # Disable live deal UF defaults so this unit test uses lead codes.
        bitrix_field_deal_total_amount="",
        bitrix_field_deal_amount_paid="",
        bitrix_field_deal_remaining_balance="",
        bitrix_field_deal_installment_count="",
        bitrix_field_deal_installment_1="",
        bitrix_field_deal_installment_2="",
        bitrix_field_deal_installment_3="",
        bitrix_field_deal_installment_4="",
        bitrix_field_deal_installment_1_date="",
        bitrix_field_deal_installment_2_due_date="",
        bitrix_field_deal_installment_3_due_date="",
        bitrix_field_deal_installment_4_due_date="",
        bitrix_field_deal_payment_1_mode="",
        bitrix_field_deal_payment_2_mode="",
        bitrix_field_deal_payment_3_mode="",
        bitrix_field_deal_payment_4_mode="",
        bitrix_field_deal_payment_link="",
        bitrix_field_deal_lead_id="",
        bitrix_field_deal_student_name="",
        bitrix_field_deal_student_mail="",
        bitrix_field_deal_student_contact="",
        bitrix_field_deal_enrollment_date="",
        bitrix_field_deal_ops_notes="",
        bitrix_field_deal_comment="",
        bitrix_field_deal_schedule_finalized="",
        bitrix_field_deal_trainer_shared="",
        bitrix_field_deal_student_type="",
        bitrix_field_deal_batch_type="",
        bitrix_field_deal_training_mode="",
        bitrix_field_deal_course_duration="",
        bitrix_field_deal_class_timing="",
        bitrix_field_deal_study_materials="",
        bitrix_field_deal_certificates_promised="",
        bitrix_field_deal_company_website="",
        bitrix_field_deal_designation="",
        bitrix_field_deal_industry_domain="",
        bitrix_field_deal_department_training="",
        bitrix_field_deal_payment_proof="",
        bitrix_field_deal_invoice_file="",
        bitrix_field_original_deal_id="",
        bitrix_field_deal_paid_status="",
        bitrix_deal_installment_count_enum_map="",
        bitrix_deal_payment_1_mode_enum_map="",
        bitrix_deal_payment_2_mode_enum_map="",
        bitrix_deal_payment_3_mode_enum_map="",
        bitrix_deal_payment_4_mode_enum_map="",
        bitrix_deal_paid_status_enum_map="",
        bitrix_deal_schedule_finalized_enum_map="",
        bitrix_deal_trainer_shared_enum_map="",
        bitrix_deal_student_type_enum_map="",
        bitrix_deal_batch_type_enum_map="",
        bitrix_deal_training_mode_enum_map="",
        bitrix_deal_department_training_enum_map="",
        bitrix_deal_industry_domain_enum_map="",
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


def test_build_deal_payment_fields_remaps_to_deal_uf_and_enums():
    from app.integrations.bitrix import build_deal_payment_fields_from_lead

    settings = Settings()
    lead = {
        "ID": "594896",
        "OPPORTUNITY": "4.20",
        "CURRENCY_ID": "AED",
        "UF_CRM_1684374599490": "4.2|AED",
        "UF_CRM_1684373846380": "2.1|AED",
        "UF_CRM_1684373986749": "2026-09-24T03:00:00+03:00",
        "UF_CRM_1684380172": "2.1|AED",
        "UF_CRM_1684374142163": "2026-09-25T03:00:00+03:00",
        "UF_CRM_1684374566210": "5828",
        "UF_CRM_1684373954405": "5774",
        "UF_CRM_1684374103659": "5794",
        "UF_CRM_1771500781458": "2.10",
    }
    fields = build_deal_payment_fields_from_lead(
        settings, lead, {"amount_paid": "2.10", "total_amount": "4.20"}
    )
    assert fields["UF_CRM_1684376313437"] == "2.1|AED"
    assert fields["UF_CRM_1684376450460"] == "2.1|AED"
    assert fields["UF_CRM_1684376591204"] == "2026-09-25T03:00:00+03:00"
    assert fields["UF_CRM_6465989F6E0EB"] == "6004"  # 2 installments
    assert fields["UF_CRM_1684376413205"] == "5856"  # Cash
    assert fields["UF_CRM_1684376704268"] == "5890"  # Tabby
    assert fields["UF_CRM_1684376291062"] == "4.2|AED"
    assert fields["UF_CRM_1789218342102"] == "594896"
    assert fields["UF_CRM_1789629158792"] == "19698"  # Partially paid


def test_build_deal_fields_copies_complete_ops_and_remaps_enums():
    from app.integrations.bitrix import build_deal_payment_fields_from_lead

    settings = Settings()
    lead = {
        "ID": "1",
        "OPPORTUNITY": "4.20",
        "CURRENCY_ID": "AED",
        "UF_CRM_1771503330575": "abinand",
        "UF_CRM_1789714405705": "a@test.com",
        "UF_CRM_1789714441645": "9072438903",
        "UF_CRM_1771503410009": "2026-09-24T03:00:00+03:00",
        "UF_CRM_1771501226065": "ops note",
        "UF_CRM_1684372587728": "comment",
        "UF_CRM_1771500430277": "12912",
        "UF_CRM_1771501047627": "12916",
        "UF_CRM_1772454738552": "13198",
        "UF_CRM_1772455024093": "13200",
        "UF_CRM_1684372786609": "5768",
        "UF_CRM_1771238558828": "To be confirmed by Ops",
        "UF_CRM_1771238691110": "To be confirmed by Ops",
        "UF_CRM_1771240157159": "To be confirmed by Ops",
        "UF_CRM_1771240323579": "To be confirmed by Ops",
        "UF_CRM_1684388099787": "To be confirmed by Ops",
        "UF_CRM_1716456659309": "it",
        "UF_CRM_1749464475095": "11826",
        "UF_CRM_1749464873149": "11758",
        "UF_CRM_1789557091401": "19700",
    }
    fields = build_deal_payment_fields_from_lead(settings, lead, {})
    assert fields["UF_CRM_6997027A88DD2"] == "abinand"
    assert fields["UF_CRM_6AAD1A163697E"] == "a@test.com"
    assert fields["UF_CRM_6AAD1A168101E"] == "9072438903"
    assert fields["UF_CRM_6996F9D3B4024"] == "12940"  # No
    assert fields["UF_CRM_6996F9DD75A95"] == "12944"  # No
    assert fields["UF_CRM_69A587F843B6B"] == "13214"  # B2C
    assert fields["UF_CRM_69A5880225A00"] == "13216"  # Public Batch
    assert fields["UF_CRM_6465989E12E11"] == "5996"  # Online
    assert fields["UF_CRM_6846B9D4E1528"] == "11890"  # Retail
    assert fields["UF_CRM_6846B9D5047AA"] == "11786"  # Operations
    assert fields["UF_CRM_1789629158792"] == "19698"
    assert fields["UF_CRM_6992F5AE7DBBD"] == "To be confirmed by Ops"
    assert fields["UF_CRM_664F1583D7579"] == "it"
