"""Test fixtures."""

import os
from collections.abc import Generator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["USE_MOCK_INTEGRATIONS"] = "true"
os.environ["PUBLIC_BASE_URL"] = "http://api.test"
os.environ["PAYMENT_FRONTEND_BASE_URL"] = "http://frontend.test"
os.environ["FRONTEND_ORIGIN"] = "http://frontend.test"
os.environ["BITRIX_WEBHOOK_SECRET"] = ""
os.environ["REMINDER_SCHEDULER_ENABLED"] = "false"
os.environ["PAYMENT_REQUIRED_PERCENT"] = "50"
os.environ["BITRIX_FINANCE_THRESHOLD_MET_STAGE_ID"] = "FINANCE_THRESHOLD_MET"

from app.config import get_settings
from app.db.session import Base, get_db
from app.main import app

SAMPLE_REGISTRANT = {
    "course_for": "self",
    "registrant_name": "Test Customer",
    "registrant_email": "customer@example.com",
    "registrant_phone": "+971500000000",
}


@pytest.fixture(autouse=True)
def reset_singletons():
    import app.integrations.factory as factory

    factory._mock_bitrix_singleton = None
    factory._mock_email_singleton = None
    get_settings.cache_clear()
    yield
    factory._mock_bitrix_singleton = None
    factory._mock_email_singleton = None
    get_settings.cache_clear()


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seed_lead():
    from app.integrations.factory import get_bitrix_client

    def _seed(lead_id: int, *, email: str = "customer@example.com", amount: Decimal = Decimal("10000")):
        bitrix = get_bitrix_client()
        bitrix.seed_lead(lead_id, email=email, name="Test Customer", amount=amount)

    return _seed
