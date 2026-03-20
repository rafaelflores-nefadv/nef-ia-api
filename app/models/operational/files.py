import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import BIGINT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OperationalBase
from app.models.operational.common import TimestampMixin, UUIDPrimaryKeyMixin


class DjangoAiRequestFile(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_request_files"
    __table_args__ = (
        CheckConstraint("file_size >= 0", name="ck_django_ai_request_files_size_nonnegative"),
    )

    analysis_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BIGINT, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DjangoAiExecutionFile(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_execution_files"
    __table_args__ = (
        CheckConstraint("file_size >= 0", name="ck_django_ai_execution_files_size_nonnegative"),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BIGINT, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class DjangoAiExecutionInputFile(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_execution_input_files"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "request_file_id",
            name="uq_django_ai_execution_input_files_execution_request",
        ),
        CheckConstraint(
            "role IN ('primary', 'context')",
            name="ck_django_ai_execution_input_files_role_valid",
        ),
        CheckConstraint(
            "order_index >= 0",
            name="ck_django_ai_execution_input_files_order_index_nonnegative",
        ),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("django_ai_request_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="context", index=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
