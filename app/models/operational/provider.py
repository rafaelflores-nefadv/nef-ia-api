import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import OperationalBase
from app.models.operational.common import TimestampMixin, UUIDPrimaryKeyMixin


class DjangoAiProvider(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_providers"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    credentials: Mapped[list["DjangoAiProviderCredential"]] = relationship(back_populates="provider")
    models: Mapped[list["DjangoAiProviderModel"]] = relationship(back_populates="provider")
    usage_rows: Mapped[list["DjangoAiProviderUsage"]] = relationship(back_populates="provider")
    balances: Mapped[list["DjangoAiProviderBalance"]] = relationship(back_populates="provider")
    token_permissions: Mapped[list["DjangoAiApiTokenPermission"]] = relationship(back_populates="provider")


class DjangoAiProviderCredential(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "credential_name",
            name="uq_django_ai_provider_credentials_name",
        ),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    credential_name: Mapped[str] = mapped_column(String(120), nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    provider: Mapped[DjangoAiProvider] = relationship(back_populates="credentials")


class DjangoAiProviderModel(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_provider_models"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "model_slug",
            name="uq_django_ai_provider_models_provider_slug",
        ),
        CheckConstraint("context_limit > 0", name="ck_django_ai_provider_models_context_limit"),
        CheckConstraint(
            "cost_input_per_1k_tokens >= 0",
            name="ck_django_ai_provider_models_cost_input_nonnegative",
        ),
        CheckConstraint(
            "cost_output_per_1k_tokens >= 0",
            name="ck_django_ai_provider_models_cost_output_nonnegative",
        ),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    context_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=8192)
    cost_input_per_1k_tokens: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    cost_output_per_1k_tokens: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    provider: Mapped[DjangoAiProvider] = relationship(back_populates="models")
    usage_rows: Mapped[list["DjangoAiProviderUsage"]] = relationship(back_populates="model")


class DjangoAiProviderUsage(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_provider_usage"
    __table_args__ = (
        CheckConstraint("input_tokens >= 0", name="ck_django_ai_provider_usage_input_tokens_nonnegative"),
        CheckConstraint("output_tokens >= 0", name="ck_django_ai_provider_usage_output_tokens_nonnegative"),
        CheckConstraint("estimated_cost >= 0", name="ck_django_ai_provider_usage_cost_nonnegative"),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_providers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_provider_models.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)

    provider: Mapped[DjangoAiProvider] = relationship(back_populates="usage_rows")
    model: Mapped[DjangoAiProviderModel] = relationship(back_populates="usage_rows")


class DjangoAiProviderBalance(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_provider_balances"
    __table_args__ = (
        UniqueConstraint("provider_id", name="uq_django_ai_provider_balances_provider_id"),
        CheckConstraint("initial_credit >= 0", name="ck_django_ai_provider_balances_initial_credit"),
        CheckConstraint("used_credit >= 0", name="ck_django_ai_provider_balances_used_credit"),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    initial_credit: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    used_credit: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)

    provider: Mapped[DjangoAiProvider] = relationship(back_populates="balances")

