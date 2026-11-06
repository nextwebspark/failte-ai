"""Platform admin tables: runtime feature switches and the audit log.

``platform_feature_flags`` holds one platform-wide row per switched product
area (``organization_id`` NULL) and optional per-organisation overrides. A
missing row means "use the default in code" (api.services.platform_admin
.features).

``platform_admin_audit_log`` records every change a platform admin makes
(feature switches, billing terms, credit, concurrency, admin grants,
impersonation). It stores ids only, no names or emails, so erasing a user
or an organisation leaves no personal data behind in it.

Fork-owned module. ``api.db.models`` imports it at the bottom so the tables
are part of ``Base.metadata`` wherever the models are loaded.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.db.models import Base


class PlatformFeatureFlagModel(Base):
    __tablename__ = "platform_feature_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # A key of api.services.platform_admin.features.FEATURES.
    feature: Mapped[str] = mapped_column(String(64))
    # NULL: the platform-wide value. Set: this organisation's override.
    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "uq_platform_feature_flags_platform",
            "feature",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
        Index(
            "uq_platform_feature_flags_organization",
            "feature",
            "organization_id",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
    )


class PlatformAdminAuditLogModel(Base):
    __tablename__ = "platform_admin_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    # An api.services.platform_admin.audit.AuditAction value.
    action: Mapped[str] = mapped_column(String(64))
    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id", ondelete="SET NULL")
    )
    target_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    # What changed, e.g. {"feature": "campaigns", "before": null, "after": true}.
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )

    __table_args__ = (
        Index("ix_platform_admin_audit_log_created_at", "created_at"),
        Index("ix_platform_admin_audit_log_organization_id", "organization_id"),
    )
