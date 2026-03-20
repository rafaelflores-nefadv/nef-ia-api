from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AutomationExecutionSettingsUpsertRequest(BaseModel):
    execution_profile: str = Field(min_length=3, max_length=20)
    is_active: bool = True
    max_execution_rows: int | None = Field(default=None, ge=1)
    max_provider_calls: int | None = Field(default=None, ge=1)
    max_text_chunks: int | None = Field(default=None, ge=1)
    max_tabular_row_characters: int | None = Field(default=None, ge=1)
    max_execution_seconds: int | None = Field(default=None, ge=1)
    max_context_characters: int | None = Field(default=None, ge=1)
    max_context_file_characters: int | None = Field(default=None, ge=1)
    max_prompt_characters: int | None = Field(default=None, ge=1)


class AutomationExecutionSettingResponse(BaseModel):
    automation_id: UUID
    automation_name: str
    automation_is_active: bool
    persisted_setting_id: UUID | None = None
    persisted_is_active: bool | None = None
    persisted_execution_profile: str | None = None
    persisted_limits_overrides: dict[str, int] = Field(default_factory=dict)
    resolved_execution_profile: str
    resolved_profile_source: str
    resolved_profile_source_details: dict[str, Any] = Field(default_factory=dict)
    resolved_limits: dict[str, int]
    hard_clamped_fields: list[str] = Field(default_factory=list)
    hard_clamp_details: dict[str, dict[str, int]] = Field(default_factory=dict)


class AutomationExecutionSettingsListResponse(BaseModel):
    generated_at: datetime
    total: int
    items: list[AutomationExecutionSettingResponse] = Field(default_factory=list)
