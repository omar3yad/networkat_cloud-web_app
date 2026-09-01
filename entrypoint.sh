#!/bin/sh
set -e

# ── Wait for PostgreSQL to be ready ─────────────────────────────────────────
# Poll the database using psycopg2 before attempting migrations.
# This is more reliable than a fixed sleep because it responds to actual
# DB readiness rather than an arbitrary time estimate.
echo "[entrypoint] Waiting for database to be ready..."
until python -c "
import psycopg2, os, sys
try:
    psycopg2.connect(os.environ['DATABASE_URL'])
    print('DB ready.')
except Exception as e:
    print(f'DB not ready: {e}')
    sys.exit(1)
"; do
    sleep 2
done

# ── Run Alembic migrations ───────────────────────────────────────────────────
echo "[entrypoint] Running Flask DB migrations..."
FLASK_APP=app.py flask db upgrade

# ── Fix ownership of any files created during migration ─────────────────────
# 'flask db upgrade' may generate new migration files or __pycache__ entries
# owned by root if the base image layer ran as root at some point.
# These two find commands bring everything under /app/migrations into
# devteam ownership and ensure group-write is set, making all devteam
# members able to edit migration files without sudo.
find /app/migrations -not -group devteam -exec chgrp devteam {} +
find /app/migrations -perm -u+w -exec chmod g+w {} +

# ── Hand off to supervisord ──────────────────────────────────────────────────
# exec replaces the shell process so supervisord becomes PID 1 and receives
# Docker stop/kill signals correctly.
echo "[entrypoint] Starting supervisord..."
exec /usr/bin/supervisord -c /app/supervisord.conf