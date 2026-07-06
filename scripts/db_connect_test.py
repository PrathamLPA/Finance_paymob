"""Test database connection using DATABASE_URL from .env."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text

from app.config import get_settings

get_settings.cache_clear()
settings = get_settings()
print(f"Connecting to: {settings.database_url.split('@')[-1]}")
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
with engine.connect() as conn:
    print("OK:", conn.execute(text("SELECT 1")).scalar())
