"""website catalogue, connection syncs, auth mode none

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10 10:53:18.881968

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = 'fallcha_tools'
AUTH_MODE_CK = 'ck_connections_auth_mode'


def upgrade() -> None:
    op.drop_constraint(op.f(AUTH_MODE_CK), 'connections', schema=SCHEMA, type_='check')
    op.create_check_constraint(
        op.f(AUTH_MODE_CK),
        'connections',
        "auth_mode IN ('oauth2', 'service_account', 'api_key', 'none')",
        schema=SCHEMA,
    )
    op.create_table('catalogue_products',
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('sku', sa.String(length=200), nullable=False),
    sa.Column('org_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('brand', sa.Text(), server_default='', nullable=False),
    sa.Column('category', sa.Text(), server_default='', nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('price', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=8), nullable=False),
    sa.Column('availability', sa.String(length=64), server_default='', nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('search', postgresql.TSVECTOR(), sa.Computed("setweight(to_tsvector('english'::regconfig, coalesce(name, '')), 'A') || setweight(to_tsvector('english'::regconfig, coalesce(brand, '')), 'B') || setweight(to_tsvector('english'::regconfig, coalesce(category, '')), 'C') || setweight(to_tsvector('english'::regconfig, coalesce(description, '')), 'D')", persisted=True), nullable=True),
    sa.ForeignKeyConstraint(['connection_id'], ['fallcha_tools.connections.id'], name=op.f('fk_catalogue_products_connection_id_connections'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('connection_id', 'sku', name=op.f('pk_catalogue_products')),
    schema='fallcha_tools'
    )
    op.create_index(op.f('ix_catalogue_products_org_id_connection_id'), 'catalogue_products', ['org_id', 'connection_id'], unique=False, schema='fallcha_tools')
    op.create_index(op.f('ix_catalogue_products_search'), 'catalogue_products', ['search'], unique=False, schema='fallcha_tools', postgresql_using='gin')
    op.create_table('connection_syncs',
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.Enum('running', 'succeeded', 'failed', name='sync_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('item_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('requested_by', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['connection_id'], ['fallcha_tools.connections.id'], name=op.f('fk_connection_syncs_connection_id_connections'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('connection_id', name=op.f('pk_connection_syncs')),
    schema='fallcha_tools'
    )
    op.create_index(op.f('ix_connection_syncs_org_id'), 'connection_syncs', ['org_id'], unique=False, schema='fallcha_tools')


def downgrade() -> None:
    op.drop_index(op.f('ix_connection_syncs_org_id'), table_name='connection_syncs', schema='fallcha_tools')
    op.drop_table('connection_syncs', schema='fallcha_tools')
    op.drop_index(op.f('ix_catalogue_products_search'), table_name='catalogue_products', schema='fallcha_tools', postgresql_using='gin')
    op.drop_index(op.f('ix_catalogue_products_org_id_connection_id'), table_name='catalogue_products', schema='fallcha_tools')
    op.drop_table('catalogue_products', schema='fallcha_tools')
    # Secret-less connections cannot exist under the old constraint.
    op.execute(
        f"UPDATE {SCHEMA}.connections SET status = 'revoked', auth_mode = 'api_key'"
        " WHERE auth_mode = 'none'"
    )
    op.drop_constraint(op.f(AUTH_MODE_CK), 'connections', schema=SCHEMA, type_='check')
    op.create_check_constraint(
        op.f(AUTH_MODE_CK),
        'connections',
        "auth_mode IN ('oauth2', 'service_account', 'api_key')",
        schema=SCHEMA,
    )
