import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OperationalBase
from app.models.operational.common import TimestampMixin, UUIDPrimaryKeyMixin


class DjangoAiAutomationExecutionSetting(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_automation_execution_settings"
    __table_args__ = (
        UniqueConstraint(
            "automation_id",
            name="uq_django_ai_automation_execution_settings_automation_id",
        ),
        CheckConstraint(
            "execution_profile IN ('standard', 'heavy', 'extended')",
            name="ck_django_ai_automation_execution_settings_profile_valid",
        ),
        CheckConstraint(
            "max_execution_rows IS NULL OR max_execution_rows > 0",
            name="ck_django_ai_automation_execution_settings_max_execution_rows_positive",
        ),
        CheckConstraint(
            "max_provider_calls IS NULL OR max_provider_calls > 0",
            name="ck_django_ai_automation_execution_settings_max_provider_calls_positive",
        ),
        CheckConstraint(
            "max_text_chunks IS NULL OR max_text_chunks > 0",
            name="ck_django_ai_automation_execution_settings_max_text_chunks_positive",
        ),
        CheckConstraint(
            "max_tabular_row_characters IS NULL OR max_tabular_row_characters > 0",
            name="ck_django_ai_automation_execution_settings_max_tabular_row_characters_positive",
        ),
        CheckConstraint(
            "max_execution_seconds IS NULL OR max_execution_seconds > 0",
            name="ck_django_ai_automation_execution_settings_max_execution_seconds_positive",
        ),
        CheckConstraint(
            "max_context_characters IS NULL OR max_context_characters > 0",
            name="ck_django_ai_automation_execution_settings_max_context_characters_positive",
        ),
        CheckConstraint(
            "max_context_file_characters IS NULL OR max_context_file_characters > 0",
            name="ck_django_ai_automation_execution_settings_max_context_file_characters_positive",
        ),
        CheckConstraint(
            "max_prompt_characters IS NULL OR max_prompt_characters > 0",
            name="ck_django_ai_automation_execution_settings_max_prompt_characters_positive",
        ),
    )

    automation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("automations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_profile: Mapped[str] = mapped_column(String(20), nullable=False, default="standard", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    max_execution_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_provider_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_text_chunks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tabular_row_characters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_execution_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_context_characters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_context_file_characters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_prompt_characters: Mapped[int | None] = mapped_column(Integer, nullable=True)
