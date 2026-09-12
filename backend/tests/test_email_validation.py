"""Email format checks and Bitrix invalid-mail comments."""

from decimal import Decimal

from app.services.email_validation import invalid_email_comment, is_valid_email


def test_is_valid_email_accepts_normal_addresses():
    assert is_valid_email("sabith.learnerspoint@gmail.com")
    assert is_valid_email("  aisha@learnerspoint.org ")


def test_is_valid_email_rejects_bad_values():
    assert not is_valid_email(None)
    assert not is_valid_email("")
    assert not is_valid_email("not-an-email")
    assert not is_valid_email("missing-domain@")
    assert not is_valid_email("spaces emma@test.com")


def test_invalid_email_comment_message():
    assert invalid_email_comment("test@gmail.com") == "test@gmail.com is not a valid mail"
    assert invalid_email_comment("") == "(empty) is not a valid mail"


def test_sync_posts_invalid_email_comment(client, seed_lead, db_session):
    import asyncio

    from app.integrations.factory import get_bitrix_client
    from app.models.customer_workflow import CustomerWorkflow
    from app.services.workflow_orchestrator import WorkflowOrchestrator
    from sqlalchemy import select

    seed_lead(593100, email="ok@test.com", amount=Decimal("100"))
    bitrix = get_bitrix_client()
    bitrix._mock_leads[593100]["EMAIL"] = [{"VALUE": "bad-email", "VALUE_TYPE": "WORK"}]
    contact_id = bitrix._mock_leads[593100].get("CONTACT_ID")
    if contact_id:
        bitrix._mock_contacts[int(contact_id)]["EMAIL"] = [
            {"VALUE": "bad-email", "VALUE_TYPE": "WORK"}
        ]
    bitrix._mock_leads[593100]["UF_CRM_1740610735352"] = ""

    orch = WorkflowOrchestrator(db_session)
    workflow = orch.get_or_create_workflow(593100)

    asyncio.run(orch.sync_workflow_from_lead(workflow, bitrix._mock_leads[593100]))

    db_session.refresh(workflow)
    assert workflow.customer_email is None
    comments = bitrix._mock_comments.get(("LEAD", 593100), [])
    assert any(c["COMMENT"] == "bad-email is not a valid mail" for c in comments)

    # Second sync must not spam another identical comment
    before = len(comments)
    asyncio.run(orch.sync_workflow_from_lead(workflow, bitrix._mock_leads[593100]))
    assert len(bitrix._mock_comments.get(("LEAD", 593100), [])) == before

    stored = db_session.scalar(
        select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 593100)
    )
    assert stored is not None
    assert stored.customer_email is None
