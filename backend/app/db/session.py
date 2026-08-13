"""Database session management."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()


def _engine_kwargs(database_url: str) -> dict:
    kwargs: dict = {"pool_pre_ping": True}
    if not database_url.startswith("postgresql"):
        return kwargs

    # Behind a transaction-pooling proxy (Railway/Supabase pgbouncer) a connection
    # can be handed to a different backend between statements, so psycopg's named
    # prepared statements collide as "prepared statement _pgN_M already exists".
    kwargs["connect_args"] = {"prepare_threshold": None}
    kwargs["pool_recycle"] = 300
    return kwargs


engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
