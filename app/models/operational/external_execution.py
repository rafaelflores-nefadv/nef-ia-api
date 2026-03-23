import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OperationalBase
from app.models.operational.common import TimestampMixin, UUIDPrimaryKeyMixin


class DjangoAiExternalExecutionContext(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_external_execution_contexts"
    __table_args__ = (
        CheckConstraint(
            "resource_type IN ('prompt', 'automation')",
            name="ck_django_ai_external_execution_contexts_resource_type_valid",
        ),
        CheckConstraint(
            "("
            "(resource_type = 'prompt' AND prompt_id IS NOT NULL)"
            " OR "
            "(resource_type = 'automation' AND prompt_id IS NULL)"
            ")",
            name="ck_django_ai_external_execution_contexts_prompt_scope_consistency",
        ),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_executions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_api_tokens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    analysis_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
