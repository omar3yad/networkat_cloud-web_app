"""add anti-abuse and trial fields to clients table

Revision ID: e4f5a6b7c8d9
Revises: 5bcdf9c22362
Create Date: 2026-09-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4f5a6b7c8d9'
down_revision = '5bcdf9c22362'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('clients', sa.Column('is_trial', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('clients', sa.Column('trial_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clients', sa.Column('trial_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clients', sa.Column('mpls_activated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clients', sa.Column('mpls_trial_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clients', sa.Column('phone_verified', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('clients', sa.Column('card_fingerprint', sa.String(length=128), nullable=True))
    op.add_column('clients', sa.Column('stripe_customer_id', sa.String(length=100), nullable=True))
    op.add_column('clients', sa.Column('stripe_payment_method_id', sa.String(length=100), nullable=True))

    op.create_unique_constraint('uq_clients_card_fingerprint', 'clients', ['card_fingerprint'])


def downgrade():
    op.drop_constraint('uq_clients_card_fingerprint', 'clients', type_='unique')
    op.drop_column('clients', 'stripe_payment_method_id')
    op.drop_column('clients', 'stripe_customer_id')
    op.drop_column('clients', 'card_fingerprint')
    op.drop_column('clients', 'phone_verified')
    op.drop_column('clients', 'mpls_trial_expires_at')
    op.drop_column('clients', 'mpls_activated_at')
    op.drop_column('clients', 'trial_expires_at')
    op.drop_column('clients', 'trial_started_at')
    op.drop_column('clients', 'is_trial')
