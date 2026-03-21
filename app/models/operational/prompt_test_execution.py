import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OperationalBase
from app.models.operational.common import TimestampMixin, UUIDPrimaryKeyMixin


class DjangoAiPromptTestExecutionContext(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_prompt_test_execution_contexts"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_executions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    test_automation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    test_automation_name: Mapped[str] = mapped_column(String(180), nullable=False)
    provider_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    model_slug: Mapped[str] = mapped_column(String(160), nullable=False)
