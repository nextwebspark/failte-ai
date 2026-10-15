"""create fallcha_tools schema

Revision ID: 0001
Revises:
Create Date: 2026-10-09 18:34:05.537476

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # env.py also creates it (the version table lives there); kept for clarity.
    op.execute("CREATE SCHEMA IF NOT EXISTS fallcha_tools")
    op.create_table('provider_apps',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.BigInteger(), nullable=True),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('client_id', sa.Text(), nullable=False),
    sa.Column('client_secret_enc', sa.Text(), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provider_apps')),
    schema='fallcha_tools'
    )
    op.create_index(op.f('ix_provider_apps_org_id_provider'), 'provider_apps', ['org_id', 'provider'], unique=False, schema='fallcha_tools')
    op.create_table('connections',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.BigInteger(), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('auth_mode', sa.Enum('oauth2', 'service_account', 'api_key', name='auth_mode', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('provider_app_id', sa.UUID(), nullable=True),
    sa.Column('account_label', sa.Text(), nullable=True),
    sa.Column('scopes_granted', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('secret_enc', sa.Text(), nullable=True),
    sa.Column('access_token_enc', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.Enum('active', 'error', 'revoked', name='connection_status', native_enum=False, create_constraint=True, length=32), server_default='active', nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['provider_app_id'], ['fallcha_tools.provider_apps.id'], name=op.f('fk_connections_provider_app_id_provider_apps'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_connections')),
    schema='fallcha_tools'
    )
    op.create_index(op.f('ix_connections_org_id_provider'), 'connections', ['org_id', 'provider'], unique=False, schema='fallcha_tools')
    op.create_table('oauth_states',
    sa.Column('state', sa.String(length=128), nullable=False),
    sa.Column('org_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('provider_app_id', sa.UUID(), nullable=True),
    sa.Column('code_verifier_enc', sa.Text(), nullable=False),
    sa.Column('redirect_uri', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['provider_app_id'], ['fallcha_tools.provider_apps.id'], name=op.f('fk_oauth_states_provider_app_id_provider_apps'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('state', name=op.f('pk_oauth_states')),
    schema='fallcha_tools'
    )
    op.create_index(op.f('ix_oauth_states_expires_at'), 'oauth_states', ['expires_at'], unique=False, schema='fallcha_tools')
    op.create_table('connection_keys',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.BigInteger(), nullable=False),
    sa.Column('fallcha_credential_uuid', sa.String(length=64), nullable=True),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['connection_id'], ['fallcha_tools.connections.id'], name=op.f('fk_connection_keys_connection_id_connections'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_connection_keys')),
    sa.UniqueConstraint('key_hash', name=op.f('uq_connection_keys_key_hash')),
    schema='fallcha_tools'
    )
    op.create_index(op.f('ix_connection_keys_connection_id'), 'connection_keys', ['connection_id'], unique=False, schema='fallcha_tools')
    op.create_index(op.f('ix_connection_keys_org_id'), 'connection_keys', ['org_id'], unique=False, schema='fallcha_tools')


def downgrade() -> None:
    # The schema itself stays: it holds alembic_version.
    op.drop_index(op.f('ix_connection_keys_org_id'), table_name='connection_keys', schema='fallcha_tools')
    op.drop_index(op.f('ix_connection_keys_connection_id'), table_name='connection_keys', schema='fallcha_tools')
    op.drop_table('connection_keys', schema='fallcha_tools')
    op.drop_index(op.f('ix_oauth_states_expires_at'), table_name='oauth_states', schema='fallcha_tools')
    op.drop_table('oauth_states', schema='fallcha_tools')
    op.drop_index(op.f('ix_connections_org_id_provider'), table_name='connections', schema='fallcha_tools')
    op.drop_table('connections', schema='fallcha_tools')
    op.drop_index(op.f('ix_provider_apps_org_id_provider'), table_name='provider_apps', schema='fallcha_tools')
    op.drop_table('provider_apps', schema='fallcha_tools')
