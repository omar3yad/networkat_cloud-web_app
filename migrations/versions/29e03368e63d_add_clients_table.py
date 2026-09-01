"""add clients table

Revision ID: 29e03368e63d
Revises: 8315e7723b3f
Create Date: 2026-07-22 11:13:48.486844

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '29e03368e63d'
down_revision = '8315e7723b3f'
branch_labels = None
depends_on = None


def upgrade():
    # 1. إنشاء جدول clients
    op.create_table('clients',
    sa.Column('user_id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('username', sa.String(length=32), nullable=False),
    sa.Column('password_hashed', sa.Text(), nullable=False),
    sa.Column('client_name', sa.String(length=100), nullable=False),
    sa.Column('client_company_name', sa.String(length=150), nullable=True),
    sa.Column('netbird_group_id', sa.String(length=100), nullable=True),
    sa.Column('client_email', sa.String(length=255), nullable=False),
    sa.Column('client_phone_number', sa.String(length=20), nullable=True),
    sa.Column('client_country', sa.String(length=100), nullable=True),
    sa.Column('subscription', sa.String(length=50), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('subnet_cidr', sa.String(length=50), nullable=True),
    sa.Column('mode', sa.String(length=50), nullable=True),
    sa.PrimaryKeyConstraint('user_id'),
    sa.UniqueConstraint('client_email'),
    sa.UniqueConstraint('client_phone_number'),
    sa.UniqueConstraint('netbird_group_id'),
    sa.UniqueConstraint('username')
    )

    # 2. تعديل الجداول وتحديد nullable=True أولاً للتعامل مع البيانات القائمة
    
    # --- dns_rules ---
    with op.batch_alter_table('dns_rules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_id', sa.BigInteger(), nullable=True))
    op.execute("UPDATE dns_rules SET client_id = customer_id WHERE client_id IS NULL AND customer_id IS NOT NULL")
    with op.batch_alter_table('dns_rules', schema=None) as batch_op:
        batch_op.alter_column('client_id', nullable=False)
        batch_op.drop_constraint(batch_op.f('dns_rules_customer_id_fkey'), type_='foreignkey')
        batch_op.create_foreign_key(None, 'clients', ['client_id'], ['user_id'], ondelete='CASCADE')
        batch_op.drop_column('customer_id')

    # --- edges ---
    with op.batch_alter_table('edges', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_id', sa.BigInteger(), nullable=True))
    op.execute("UPDATE edges SET client_id = customer_id WHERE client_id IS NULL AND customer_id IS NOT NULL")
    with op.batch_alter_table('edges', schema=None) as batch_op:
        batch_op.alter_column('client_id', nullable=False)
        batch_op.drop_constraint(batch_op.f('uq_customer_edge_name'), type_='unique')
        batch_op.drop_constraint(batch_op.f('uq_customer_ip'), type_='unique')
        batch_op.create_unique_constraint('uq_client_edge_name', ['client_id', 'edge_name'])
        batch_op.create_unique_constraint('uq_client_ip', ['client_id', 'assigned_ip'])
        batch_op.drop_constraint(batch_op.f('edges_customer_id_fkey'), type_='foreignkey')
        batch_op.create_foreign_key(None, 'clients', ['client_id'], ['user_id'], ondelete='CASCADE')
        batch_op.drop_column('customer_id')

    # --- firewall_rules ---
    with op.batch_alter_table('firewall_rules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_id', sa.BigInteger(), nullable=True))
    op.execute("UPDATE firewall_rules SET client_id = customer_id WHERE client_id IS NULL AND customer_id IS NOT NULL")
    with op.batch_alter_table('firewall_rules', schema=None) as batch_op:
        batch_op.alter_column('client_id', nullable=False)
        batch_op.drop_constraint(batch_op.f('firewall_rules_customer_id_fkey'), type_='foreignkey')
        batch_op.create_foreign_key(None, 'clients', ['client_id'], ['user_id'], ondelete='CASCADE')
        batch_op.drop_column('customer_id')

    # --- policies ---
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_id', sa.BigInteger(), nullable=True))
    op.execute("UPDATE policies SET client_id = customer_id WHERE client_id IS NULL AND customer_id IS NOT NULL")
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.alter_column('client_id', nullable=False)
        batch_op.drop_constraint(batch_op.f('policies_customer_id_fkey'), type_='foreignkey')
        batch_op.create_foreign_key(None, 'clients', ['client_id'], ['user_id'], ondelete='CASCADE')
        batch_op.drop_column('customer_id')

    # --- tokens ---
    with op.batch_alter_table('tokens', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_id', sa.BigInteger(), nullable=True))
    op.execute("UPDATE tokens SET client_id = customer_id WHERE client_id IS NULL AND customer_id IS NOT NULL")
    with op.batch_alter_table('tokens', schema=None) as batch_op:
        batch_op.alter_column('client_id', nullable=False)
        batch_op.drop_constraint(batch_op.f('tokens_customer_id_fkey'), type_='foreignkey')
        batch_op.create_foreign_key(None, 'clients', ['client_id'], ['user_id'], ondelete='CASCADE')
        batch_op.drop_column('customer_id')

    # 3. مسح الجداول القديمة
    op.drop_table('client_users')
    op.drop_table('customer_users')
    op.drop_table('customers')
    
def downgrade():
    op.create_table('customers',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('name', sa.VARCHAR(length=255), autoincrement=False, nullable=False),
    sa.Column('subnet_cidr', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
    sa.Column('mode', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
    sa.Column('phone', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('netbird_group_id', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('customers_pkey')),
    sa.UniqueConstraint('name', name=op.f('customers_name_key')),
    sa.UniqueConstraint('netbird_group_id', name=op.f('customers_netbird_group_id_key'))
    )

    op.create_table('customer_users',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('customer_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('username', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
    sa.Column('password_hash', sa.VARCHAR(length=255), autoincrement=False, nullable=False),
    sa.Column('salt', sa.VARCHAR(length=64), autoincrement=False, nullable=False),
    sa.Column('last_login', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('customer_users_customer_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('customer_users_pkey')),
    sa.UniqueConstraint('username', name=op.f('customer_users_username_key'))
    )

    op.create_table('client_users',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('username', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
    sa.Column('password_hash', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('customer_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('last_login', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('client_users_customer_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('client_users_pkey')),
    sa.UniqueConstraint('username', name=op.f('client_users_username_key'))
    )

    with op.batch_alter_table('tokens', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_id', sa.INTEGER(), autoincrement=False, nullable=False))
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(batch_op.f('tokens_customer_id_fkey'), 'customers', ['customer_id'], ['id'], ondelete='CASCADE')
        batch_op.drop_column('client_id')

    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_id', sa.INTEGER(), autoincrement=False, nullable=False))
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(batch_op.f('policies_customer_id_fkey'), 'customers', ['customer_id'], ['id'], ondelete='CASCADE')
        batch_op.drop_column('client_id')

    with op.batch_alter_table('firewall_rules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_id', sa.INTEGER(), autoincrement=False, nullable=False))
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(batch_op.f('firewall_rules_customer_id_fkey'), 'customers', ['customer_id'], ['id'])
        batch_op.drop_column('client_id')

    with op.batch_alter_table('edges', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_id', sa.INTEGER(), autoincrement=False, nullable=False))
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(batch_op.f('edges_customer_id_fkey'), 'customers', ['customer_id'], ['id'], ondelete='CASCADE')
        batch_op.drop_constraint('uq_client_ip', type_='unique')
        batch_op.drop_constraint('uq_client_edge_name', type_='unique')
        batch_op.create_unique_constraint(batch_op.f('uq_customer_ip'), ['customer_id', 'assigned_ip'])
        batch_op.create_unique_constraint(batch_op.f('uq_customer_edge_name'), ['customer_id', 'edge_name'])
        batch_op.drop_column('client_id')

    with op.batch_alter_table('dns_rules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_id', sa.INTEGER(), autoincrement=False, nullable=False))
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(batch_op.f('dns_rules_customer_id_fkey'), 'customers', ['customer_id'], ['id'])
        batch_op.drop_column('client_id')

    op.drop_table('clients')