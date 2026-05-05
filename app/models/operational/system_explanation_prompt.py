from sqlalchemy import Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OperationalBase
from app.models.operational.common import TimestampMixin, UUIDPrimaryKeyMixin


class DjangoAiSystemExplanationPrompt(UUIDPrimaryKeyMixin, TimestampMixin, OperationalBase):
    __tablename__ = "django_ai_system_explanation_prompts"

    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
