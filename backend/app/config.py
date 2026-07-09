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
    bitrix_sales_pipeline_id: str = ""
    bitrix_finance_pipeline_id: str = ""
    bitrix_b2c_pipeline_id: str = ""
    bitrix_field_invoice_reference: str = "UF_CRM_INVOICE_REFERENCE"
    bitrix_field_invoice_url: str = "UF_CRM_INVOICE_URL"
    bitrix_field_amount_paid: str = "UF_CRM_AMOUNT_PAID"
    bitrix_field_remaining_balance: str = "UF_CRM_REMAINING_BALANCE"
    bitrix_field_total_amount: str = "UF_CRM_TOTAL_AMOUNT"
    bitrix_field_payment_link: str = "UF_CRM_PAYMENT_LINK"
    bitrix_field_customer_email: str = "UF_CRM_CUSTOMER_EMAIL"

    # Paymob
    paymob_api_key: str = ""
    paymob_secret_key: str = ""
    paymob_public_key: str = ""
    paymob_integration_id: int = 0
    paymob_hmac_secret: str = ""
    paymob_base_url: str = "https://accept.paymob.com"
    paymob_checkout_base_url: str = "https://accept.paymob.com/unifiedcheckout/"

    # Zoho Books
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_organization_id: str = ""
    zoho_accounts_url: str = "https://accounts.zoho.com"
    zoho_books_api_url: str = "https://www.zohoapis.com/books/v3"

    # Email
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "finance@example.com"
    sendgrid_from_name: str = "Finance Team"

    # Workflow
    terms_version: str = "1.0"
    refund_policy_url: str = "https://learnerspoint.org/refund-policy"
    payment_session_ttl_hours: int = 72
    default_currency: str = "AED"
    storage_path: str = "storage"

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
