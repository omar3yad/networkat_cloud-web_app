"""rename subscription_plans columns

peer_limit    -> allowed_peers_count
billing_cycles -> billing_cycle
price_yearly   -> price_annual

Revision ID: 5bcdf9c22362
Revises: d176ccb2b6f1
Create Date: 2026-09-09 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '5bcdf9c22362'
down_revision = 'd176ccb2b6f1'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('subscription_plans', 'peer_limit',     new_column_name='allowed_peers_count')
    op.alter_column('subscription_plans', 'billing_cycles', new_column_name='billing_cycle')
    op.alter_column('subscription_plans', 'price_yearly',   new_column_name='price_annual')


def downgrade():
    op.alter_column('subscription_plans', 'allowed_peers_count', new_column_name='peer_limit')
    op.alter_column('subscription_plans', 'billing_cycle',       new_column_name='billing_cycles')
    op.alter_column('subscription_plans', 'price_annual',        new_column_name='price_yearly')
