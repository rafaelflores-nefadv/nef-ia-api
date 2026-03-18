import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import OperationalBase
from app.models.operational.common import TimestampMixin, UUIDPrimaryKeyMixin


class DjangoAiApiToken(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_api_tokens"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    created_by_user: Mapped["DjangoAiUser"] = relationship(back_populates="api_tokens")
    permissions: Mapped[list["DjangoAiApiTokenPermission"]] = relationship(back_populates="token")
    logs: Mapped[list["DjangoAiApiTokenLog"]] = relationship(back_populates="token")


class DjangoAiIntegrationToken(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_integration_tokens"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    created_by_user: Mapped["DjangoAiUser"] = relationship(back_populates="integration_tokens")


class DjangoAiApiTokenPermission(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_api_token_permissions"
    __table_args__ = (
        UniqueConstraint(
            "token_id",
            "automation_id",
            "provider_id",
            name="uq_django_ai_api_token_permissions_scope",
        ),
    )

    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_api_tokens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    automation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("automations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_providers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    allow_execution: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_file_upload: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    token: Mapped[DjangoAiApiToken] = relationship(back_populates="permissions")
    provider: Mapped["DjangoAiProvider | None"] = relationship(back_populates="token_permissions")


class DjangoAiApiTokenLog(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_api_token_logs"
    __table_args__ = (
        CheckConstraint("status_code >= 100", name="ck_django_ai_api_token_logs_status_code_min"),
    )

    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_api_tokens.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    token: Mapped[DjangoAiApiToken | None] = relationship(back_populates="logs")
