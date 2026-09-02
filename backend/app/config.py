"""Application configuration from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.db.url import resolve_supabase_url

# backend/app/config.py → repo root (Finance Project LPA)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            str(_REPO_ROOT / ".env"),
            str(_BACKEND_ROOT / ".env"),
            ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Finance Automation"
    app_env: str = "development"
    # Set automatically by Railway; lets logs prove which commit is running.
    railway_git_commit_sha: str = ""
    log_level: str = "INFO"
    # Public URL of this API service (webhooks, Paymob notification_url)
    public_base_url: str = "http://localhost:8001"
    # Customer payment pages (Railway frontend service)
    payment_frontend_base_url: str = "http://localhost:3000"
    # Allowed browser origin for CORS (frontend)
    frontend_origin: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg://finance:finance@localhost:5432/finance_automation"

    use_mock_integrations: bool = True

    # Bitrix24
    bitrix24_webhook_url: str = ""
    bitrix_webhook_secret: str = ""
    bitrix_lead_payment_stage_id: str = "LEAD_PAYMENT"
    bitrix_finance_generate_link_stage_id: str = "FINANCE_GENERATE_LINK"
    # Bitrix deal CATEGORY_ID for "Sales" (the convert-to-deal picker)
    bitrix_sales_pipeline_id: str = "16"
    bitrix_finance_pipeline_id: str = ""
    bitrix_b2c_pipeline_id: str = ""
    bitrix_field_invoice_reference: str = "UF_CRM_INVOICE_REFERENCE"
    bitrix_field_invoice_url: str = "UF_CRM_INVOICE_URL"
    bitrix_field_amount_paid: str = "UF_CRM_AMOUNT_PAID"
    bitrix_field_remaining_balance: str = "UF_CRM_REMAINING_BALANCE"
    bitrix_field_total_amount: str = "UF_CRM_TOTAL_AMOUNT"
    bitrix_field_payment_link: str = "UF_CRM_PAYMENT_LINK"
    bitrix_field_customer_email: str = "UF_CRM_CUSTOMER_EMAIL"
    # Client email on the lead (Bitrix name="UF_CRM_1740610735352")
    bitrix_field_client_email: str = "UF_CRM_1740610735352"
    bitrix_field_payment_percentage: str = "UF_CRM_PAYMENT_PERCENTAGE"
    bitrix_field_payment_status: str = "UF_CRM_PAYMENT_STATUS"
    bitrix_field_transaction_id: str = "UF_CRM_TRANSACTION_ID"
    # Stage to move finance deal to once required payment % is met
    bitrix_finance_threshold_met_stage_id: str = "FINANCE_THRESHOLD_MET"
    bitrix_field_customer_phone: str = "UF_CRM_CUSTOMER_PHONE"
    bitrix_field_customer_name: str = "UF_CRM_CUSTOMER_NAME"
    # Optional custom field holding the amount when OPPORTUNITY is empty
    bitrix_field_lead_amount: str = ""
    # Lead Payment Section — first payment link uses Installment 1 when set
    bitrix_field_installment_count: str = "UF_CRM_1684374566210"
    # Number Of Installments is a Bitrix list field — API returns enum IDs, not 1–4.
    bitrix_installment_count_enum_map: str = "5826:1,5828:2,5830:3,5832:4"
    # Payment Installment 1 amount (money). Do NOT use Payment 1 Mode here.
    bitrix_field_installment_1: str = "UF_CRM_1684373846380"
    bitrix_field_installment_2: str = "UF_CRM_1684380172"
    bitrix_field_installment_3: str = "UF_CRM_1684380201"
    bitrix_field_installment_4: str = "UF_CRM_1684380220"
    bitrix_field_installment_1_date: str = "UF_CRM_1684373986749"
    bitrix_field_installment_2_due_date: str = "UF_CRM_1684374142163"
    bitrix_field_installment_3_due_date: str = "UF_CRM_1684374296635"
    bitrix_field_installment_4_due_date: str = "UF_CRM_1684374497754"
    # Payment mode fields (enumeration — not amounts)
    bitrix_field_payment_1_mode: str = "UF_CRM_1684373954405"
    bitrix_field_payment_2_mode: str = "UF_CRM_1684374103659"
    bitrix_field_payment_3_mode: str = "UF_CRM_1684374256836"
    bitrix_field_payment_4_mode: str = "UF_CRM_1684374451274"
    # Payment mode list enum IDs → labels (Cash / Online / …)
    # Learners Point live enums (from crm.lead.userfield.list / payment mode field).
    bitrix_payment_mode_enum_map: str = (
        "5774:cash,5786:cash,"
        "5776:website_payment,13234:website_payment,"
        "13156:card,5788:online,"
        "5778:bank_transfer,5790:bank_transfer,"
        "5782:tabby,5784:tamara,"
        "5780:purchase_order,13146:others,"
        "13178:bank_installment"
    )
    # Comma-separated Bitrix enum IDs treated as Cash (skip Paymob, enqueue cash desk)
    # 5774 is the Cash ID currently returned by Learners Point Bitrix for Payment 1 Mode.
    cash_mode_enum_ids: str = "5774,5786"
    # Comma-separated Bitrix enum IDs treated as Bank Transfer (payment link + receipt upload)
    bank_transfer_mode_enum_ids: str = "5778,5790"
    # Shown on the candidate receipt-upload page after Terms
    bank_transfer_instructions: str = (
        "Please transfer the amount to the Learners Point bank account, "
        "then upload a clear photo or PDF of the transfer receipt."
    )
    # Cash Desk staff JWT + bootstrap manager
    staff_jwt_secret: str = ""
    staff_jwt_ttl_hours: int = 12
    staff_bootstrap_manager_email: str = ""
    staff_bootstrap_manager_password: str = ""
    staff_bootstrap_manager_name: str = "Cash Desk Manager"
    # Cash Desk Next.js origin (CORS) — comma-separated with frontend_origin if needed
    cashdesk_origin: str = "http://localhost:3001"
    # When true: payment link is only sent after catalog price check + Estimate create
    bitrix_price_gate_enabled: bool = True
    # Sender address for Bitrix mail.message.send (must exist in mail.mailbox.senders)
    bitrix_mail_from: str = ""
    # Used when the lead owner has no department manager email
    bitrix_approval_fallback_email: str = ""
    # How long a manager approval link stays valid
    price_approval_ttl_hours: int = 72
    # Temporary diagnostics: logs fetched lead/deal fields (may contain customer PII).
    log_bitrix_payloads: bool = False

    # Paymob
    # Temporary diagnostics: dumps the transaction object when HMAC verification fails.
    log_paymob_payloads: bool = False
    # Temporary: if HMAC fails (UAE Intention body hmac undocumented), confirm via
    # Paymob Transaction Inquiry using the API key. Turn off once Paymob documents
    # the Intention HMAC formula and verification matches again.
    paymob_hmac_fallback_to_inquiry: bool = True
    paymob_api_key: str = ""
    paymob_secret_key: str = ""
    paymob_public_key: str = ""
    # Default / card integration (Learners Point UAE Paymob)
    paymob_integration_id: int = 49586
    paymob_integration_id_card: int = 49586
    paymob_integration_id_tabby: int = 52169
    paymob_integration_id_tamara: int = 52266
    paymob_hmac_secret: str = ""
    paymob_base_url: str = "https://accept.paymob.com"
    paymob_checkout_base_url: str = "https://accept.paymob.com/unifiedcheckout/"

    # Zoho Books (https://www.zoho.com/books/api/v3/oauth/)
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_organization_id: str = ""
    # Data center: .com / .ae / .eu / .in — must match the Zoho Books org region
    zoho_accounts_url: str = "https://accounts.zoho.com"
    zoho_books_api_url: str = "https://www.zohoapis.com/books/v3"
    # Must match the redirect URI registered on the Zoho API Console client
    zoho_oauth_redirect_uri: str = ""
    zoho_oauth_scopes: str = (
        "ZohoBooks.contacts.CREATE,ZohoBooks.contacts.READ,"
        "ZohoBooks.invoices.CREATE,ZohoBooks.invoices.READ,ZohoBooks.invoices.UPDATE,"
        "ZohoBooks.customerpayments.CREATE,ZohoBooks.settings.READ"
    )
    # Optional catalog item; if empty, invoices use ad-hoc line items
    zoho_default_item_id: str = ""

    # Email
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "finance@example.com"
    sendgrid_from_name: str = "Finance Team"

    # Workflow
    terms_version: str = "1.0"
    refund_policy_url: str = (
        "https://financepaymob-frontend-production.up.railway.app/terms-and-conditions"
    )
    # After a successful "for myself" payment, thank-you page links here
    lms_login_url: str = (
        "https://learn.learnerspoint.org/auth/login"
        "?redirect=https%3A%2F%2Flearn.learnerspoint.org%2Fmy-classroom"
    )
    payment_session_ttl_hours: int = 72
    default_currency: str = "AED"
    storage_path: str = "storage"
    # Minimum paid % of total before customer may proceed (e.g. 50)
    payment_required_percent: float = 50.0
    # Automated payment reminders
    reminder_enabled: bool = True
    reminder_interval_hours: int = 24
    reminder_scheduler_enabled: bool = True
    reminder_scheduler_poll_seconds: int = 300
    # When the plan is installments, also email the client on each due date
    installment_due_notices_enabled: bool = True

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        return value

    @model_validator(mode="after")
    def resolve_supabase_database_url(self) -> "Settings":
        self.database_url = resolve_supabase_url(self.database_url)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
