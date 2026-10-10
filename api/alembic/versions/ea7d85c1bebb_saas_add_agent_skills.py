"""saas_add_agent_skills

Revision ID: ea7d85c1bebb
Revises: 6b0c8484ba5a
Create Date: 2026-10-10 18:00:00.000000

Agent skills (see api/db/skill_models.py): the platform library
(skill_library, skill_library_files; no organization_id) and
organization-scoped workspace skills (skills, skill_files). Workspace skill
names are unique per organization among non-archived rows (partial index).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ea7d85c1bebb"
down_revision: str | None = "6b0c8484ba5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_library",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("library_skill_uuid", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="draft", nullable=False
        ),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("frontmatter_extra", sa.JSON(), nullable=True),
        sa.Column("seed_hash", sa.String(length=64), nullable=True),
        sa.Column("published_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'deprecated')",
            name="ck_skill_library_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("library_skill_uuid"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "skill_library_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("library_skill_uuid", sa.String(length=36), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["library_skill_uuid"],
            ["skill_library.library_skill_uuid"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "library_skill_uuid", "path", name="uq_skill_library_files_skill_path"
        ),
    )
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("skill_uuid", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="active", nullable=False
        ),
        sa.Column("allowed_tool_uuids", sa.JSON(), nullable=True),
        sa.Column("frontmatter_extra", sa.JSON(), nullable=True),
        sa.Column("source_library_uuid", sa.String(length=36), nullable=True),
        sa.Column("source_version", sa.Integer(), nullable=True),
        sa.Column(
            "is_modified", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_skills_status"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_library_uuid"],
            ["skill_library.library_skill_uuid"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_uuid"),
    )
    op.create_index(
        "uq_skills_org_name_active",
        "skills",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("status <> 'archived'"),
    )
    op.create_index("ix_skills_organization_id", "skills", ["organization_id"])
    op.create_index("ix_skills_source_library_uuid", "skills", ["source_library_uuid"])
    op.create_table(
        "skill_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("skill_uuid", sa.String(length=36), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_uuid"], ["skills.skill_uuid"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_uuid", "path", name="uq_skill_files_skill_path"),
    )


def downgrade() -> None:
    op.drop_table("skill_files")
    op.drop_index("ix_skills_source_library_uuid", table_name="skills")
    op.drop_index("ix_skills_organization_id", table_name="skills")
    op.drop_index(
        "uq_skills_org_name_active",
        table_name="skills",
        postgresql_where=sa.text("status <> 'archived'"),
    )
    op.drop_table("skills")
    op.drop_table("skill_library_files")
    op.drop_table("skill_library")
