#!/bin/sh
set -eu

python - <<'PY'
import socket
import time

host = "postgres"
port = 5432
for attempt in range(30):
    try:
        with socket.create_connection((host, port), timeout=2):
            break
    except OSError:
        if attempt == 29:
            raise
        time.sleep(1)
PY

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
