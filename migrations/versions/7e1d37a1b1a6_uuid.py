"""uuid

Revision ID: 7e1d37a1b1a6
Revises: 26c050e017a8
Create Date: 2026-07-23 13:49:44.807948
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '7e1d37a1b1a6'
down_revision = '26c050e017a8'
branch_labels = None
depends_on = None

child_tables = ['dns_rules', 'edges', 'firewall_rules', 'policies', 'tokens']


def upgrade():
    # 1. تفعيل امتداد UUID
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

    # 2. حذف قيود المفاتيح الأجنبية (Foreign Keys) مؤقتاً
    for table in child_tables:
        op.drop_constraint(f'{table}_client_id_fkey', table, type_='foreignkey')

    # 3. حذف الـ Default القديم (Auto-increment)
    op.execute('ALTER TABLE clients ALTER COLUMN user_id DROP DEFAULT;')
    for table in child_tables:
        op.execute(f'ALTER TABLE {table} ALTER COLUMN client_id DROP DEFAULT;')

    # 4. تحويل user_id في جدول clients إلى UUID
    # التحويل عبر to_hex يضمن بقاء العلاقة سليمة بين الصفوف القديمة
    op.alter_column(
        'clients', 'user_id',
        existing_type=sa.BIGINT(),
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using="lpad(to_hex(user_id), 32, '0')::uuid",
        existing_nullable=False
    )

    # 5. تحويل client_id في الجداول التابعة إلى UUID بنفس الطريقة
    for table in child_tables:
        op.alter_column(
            table, 'client_id',
            existing_type=sa.BIGINT(),
            type_=postgresql.UUID(as_uuid=True),
            postgresql_using="lpad(to_hex(client_id), 32, '0')::uuid",
            existing_nullable=False
        )

    # 6. إعادة إنشاء قيود الـ Foreign Key
    for table in child_tables:
        op.create_foreign_key(
            f'{table}_client_id_fkey',
            table, 'clients',
            ['client_id'], ['user_id'],
            ondelete='CASCADE'
        )


def downgrade():
    for table in child_tables:
        op.drop_constraint(f'{table}_client_id_fkey', table, type_='foreignkey')

    for table in child_tables:
        op.alter_column(
            table, 'client_id',
            existing_type=postgresql.UUID(as_uuid=True),
            type_=sa.BIGINT(),
            existing_nullable=False
        )

    op.alter_column(
        'clients', 'user_id',
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.BIGINT(),
        existing_nullable=False
    )

    for table in child_tables:
        op.create_foreign_key(
            f'{table}_client_id_fkey',
            table, 'clients',
            ['client_id'], ['user_id'],
            ondelete='CASCADE'
        )