"""create system_settings table

Revision ID: f1a2b3c4d5e6
Revises: e4f5a6b7c8d9
Create Date: 2026-09-28 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


# Default settings to seed on first install
DEFAULTS = [
    # Trial Feature Gating
    ("trial.log_limit",          "3",     "integer", "Trial log limit",
     "Max system log entries shown to trial accounts",          "Trial"),
    ("trial.mpls_days",          "3",     "integer", "MPLS trial duration (days)",
     "Number of days a trial account may use MPLS routing",    "Trial"),

    # Service Enable/Disable Flags
    ("feature.system_logs",      "true",  "boolean", "System logs enabled",
     "Allow clients to access system logs page",                "Features"),
    ("feature.firewall",         "true",  "boolean", "Firewall rules enabled",
     "Allow clients to manage firewall rules",                  "Features"),
    ("feature.web_filter",       "true",  "boolean", "Web filter enabled",
     "Allow clients to use web filtering",                      "Features"),
    ("feature.mpls_routing",     "true",  "boolean", "MPLS routing enabled",
     "Allow clients to create MPLS routes",                     "Features"),
    ("feature.aliases",          "true",  "boolean", "DNS aliases enabled",
     "Allow clients to manage DNS aliases",                     "Features"),

    # Subscription Lifecycle
    ("subscription.grace_period_days", "7", "integer", "Grace period (days)",
     "Days after renewal date before account is suspended",     "Subscription"),
    ("subscription.renewal_reminder_days", "7", "integer", "Renewal reminder (days)",
     "Days before renewal date to send reminder email",         "Subscription"),

    # General
    ("app.contact_url", "/contact", "string", "Upgrade / contact URL",
     "URL shown to trial users on upgrade prompts",             "General"),
]


def upgrade():
    op.create_table(
        'system_settings',
        sa.Column('key',        sa.String(100),  primary_key=True),
        sa.Column('value',      sa.Text(),       nullable=False),
        sa.Column('value_type', sa.String(20),   nullable=False, server_default='string'),
        sa.Column('label',      sa.String(200),  nullable=False, server_default=''),
        sa.Column('description', sa.Text(),      nullable=True),
        sa.Column('category',   sa.String(100),  nullable=False, server_default='General'),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column('updated_by', sa.String(100),  nullable=True),
    )

    # Seed default values
    conn = op.get_bind()
    now = datetime.utcnow()
    for key, value, vtype, label, desc, category in DEFAULTS:
        conn.execute(
            sa.text(
                "INSERT INTO system_settings "
                "(key, value, value_type, label, description, category, updated_at) "
                "VALUES (:key, :value, :vtype, :label, :desc, :cat, :now) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "value": value, "vtype": vtype,
             "label": label, "desc": desc, "cat": category, "now": now}
        )


def downgrade():
    op.drop_table('system_settings')
