#!/bin/sh
set -eu

python - <<'PY'
import asyncio
import os
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise SystemExit("DATABASE_URL is required")


async def database_ready():
    engine = create_async_engine(database_url, connect_args={"timeout": 3})
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


for attempt in range(60):
    try:
        asyncio.run(database_ready())
        break
    except Exception:
        if attempt == 59:
            raise SystemExit("PostgreSQL did not become ready") from None
        time.sleep(2)
PY

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
