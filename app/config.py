"""Application configuration from environment variables."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Finance Automation"
    app_env: str = "development"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"

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

    # Paymob
    paymob_api_key: str = ""
    paymob_secret_key: str = ""
    paymob_public_key: str = ""
    paymob_integration_id: int = 0
    paymob_hmac_secret: str = ""
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
