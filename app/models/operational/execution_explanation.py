import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OperationalBase
from app.models.operational.common import TimestampMixin, UUIDPrimaryKeyMixin


class DjangoAiExecutionExplanation(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_execution_explanations"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            name="uq_django_ai_execution_explanations_execution_id",
        ),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    simple_explanation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
