"""group_peers.adguard_password default -> 'adguard-api'

Revision ID: a1b2c3d4e5f6
Revises: f0a0a6b4b67c
Create Date: 2026-09-01 21:40:00.000000

The original add_group_peers_table migration (f0a0a6b4b67c) set the column
server_default to 'default_password', but the running cluster and the app
(fastapi_app/services/adguard/adguard_service.py, which treats both
'default_password' and 'adguard-api' as "not yet discovered") standardised on
'adguard-api'. The GroupPeer model default was also stale. This makes the DB
default match reality for any fresh rebuild. Only the column DEFAULT changes;
existing rows are not touched (they are mirrored from netbird_db by the
sdwan_peers_sub logical replication and repopulated on demand).
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f0a0a6b4b67c'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE group_peers ALTER COLUMN adguard_password SET DEFAULT 'adguard-api';")


def downgrade():
    op.execute("ALTER TABLE group_peers ALTER COLUMN adguard_password SET DEFAULT 'default_password';")
