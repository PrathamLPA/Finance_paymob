"""Integration factory — selects mock or real implementations."""

from app.config import Settings, get_settings
from app.integrations.bitrix import MockBitrixClient, RealBitrixClient
from app.integrations.email import MockEmailClient, RealEmailClient
from app.integrations.paymob import MockPaymobClient, RealPaymobClient
from app.integrations.zoho import MockZohoBooksClient, RealZohoBooksClient

_mock_bitrix_singleton: MockBitrixClient | None = None
_mock_email_singleton: MockEmailClient | None = None


def get_bitrix_client(settings: Settings | None = None):
    global _mock_bitrix_singleton
    settings = settings or get_settings()
    if settings.use_mock_integrations or not settings.bitrix24_webhook_url:
        if _mock_bitrix_singleton is None:
            _mock_bitrix_singleton = MockBitrixClient(settings)
        return _mock_bitrix_singleton
    return RealBitrixClient(settings)


def get_paymob_client(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.use_mock_integrations or not settings.paymob_api_key:
        return MockPaymobClient(settings)
    return RealPaymobClient(settings)


def get_zoho_client(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.use_mock_integrations or not settings.zoho_refresh_token:
        return MockZohoBooksClient(settings)
    return RealZohoBooksClient(settings)


def get_email_client(settings: Settings | None = None):
    global _mock_email_singleton
    settings = settings or get_settings()
    if settings.use_mock_integrations or not settings.sendgrid_api_key:
        if _mock_email_singleton is None:
            _mock_email_singleton = MockEmailClient(settings)
        return _mock_email_singleton
    return RealEmailClient(settings)
