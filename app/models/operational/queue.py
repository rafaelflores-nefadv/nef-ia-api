import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import ExecutionStatus
from app.db.base import OperationalBase
from app.models.operational.common import TimestampMixin, UUIDPrimaryKeyMixin


class DjangoAiQueueJob(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_queue_jobs"
    __table_args__ = (
        CheckConstraint("retry_count >= 0", name="ck_django_ai_queue_jobs_retry_count_nonnegative"),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_request_files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    job_status: Mapped[str] = mapped_column(String(32), nullable=False, default=ExecutionStatus.PENDING.value, index=True)
    worker_name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_override_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
