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

# ── Best-effort: keep migration files group-writable ────────────────────────
# 'flask db upgrade' may generate new migration files / __pycache__ entries,
# and on a dev host a team member (e.g. UID 1000) may have created a
# migration on the bind mount that this container's appuser (UID 1001) does
# NOT own. chgrp/chmod require being the file OWNER (group membership isn't
# enough), so those files make the find fail — and under `set -e` that
# silently kills the container before supervisord ever starts (a 502 with no
# real error in the logs, just "Operation not permitted" chmod warnings).
# This is a convenience pass, never a hard dependency: any file this appuser
# can't touch is fixed on the host instead (compose bind mount is
# group-writable + has a default ACL; see ha_scripts/lib/common.sh's
# ensure_group_writable). So: best-effort, never fatal.
find /app/migrations -not -group devteam -exec chgrp devteam {} + 2>/dev/null || true
find /app/migrations -perm -u+w -exec chmod g+w {} + 2>/dev/null || true

# ── Hand off to supervisord ──────────────────────────────────────────────────
# exec replaces the shell process so supervisord becomes PID 1 and receives
# Docker stop/kill signals correctly.
echo "[entrypoint] Starting supervisord..."
exec /usr/bin/supervisord -c /app/supervisord.conf