"""Find the correct Supabase session pooler region for DATABASE_URL."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import get_settings

REGIONS = [
    "ap-south-1",
    "ap-southeast-1",
    "eu-central-1",
    "eu-west-1",
    "eu-west-2",
    "us-east-1",
    "us-west-1",
    "sa-east-1",
    "ap-northeast-1",
]

get_settings.cache_clear()
settings = get_settings()
base = make_url(settings.database_url)
project_ref = "qtfqhtljxzmqzwiukztr"

for region in REGIONS:
    host = f"aws-0-{region}.pooler.supabase.com"
    url = base.set(
        host=host,
        username=f"postgres.{project_ref}",
        query={"sslmode": "require"},
    )
    print(f"Trying {region}...", end=" ", flush=True)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 8})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("OK")
        print("USE_THIS_REGION", region)
        print("HOST", host)
        break
    except Exception as exc:
        print("FAIL", str(exc).split("\n")[0][:100])
else:
    print("No working pooler region found. Copy Session pooler URI from Supabase dashboard.")
    sys.exit(1)
