from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.constants import ExecutionStatus


class AutomationRuntimeItemResponse(BaseModel):
    automation_id: UUID
    automation_name: str
    automation_slug: str | None = None
    automation_is_active: bool
    owner_token_name: str | None = None
    is_test_automation: bool = False
    prompt_available: bool
    prompt_id: UUID | None = None
    prompt_is_active: bool | None = None
    prompt_version: int | None = None
    prompt_summary: str | None = None
    provider_id: UUID | None = None
    model_id: UUID | None = None
    credential_id: UUID | None = None
    credential_name: str | None = None
    provider_slug: str | None = None
    model_slug: str | None = None
    output_type: str | None = None
    result_parser: str | None = None
    result_formatter: str | None = None
    output_schema: dict[str, Any] | str | None = None
    debug_enabled: bool | None = None
    latest_analysis_request_id: UUID | None = None


class AutomationRuntimeDetailResponse(AutomationRuntimeItemResponse):
    prompt_text: str | None = None


class AutomationRuntimeUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider_id: UUID | None = None
    model_id: UUID | None = None
    credential_id: UUID | None = None
    output_type: str | None = Field(default=None, min_length=1, max_length=64)
    result_parser: str | None = Field(default=None, min_length=1, max_length=64)
    result_formatter: str | None = Field(default=None, min_length=1, max_length=64)
    output_schema: dict[str, Any] | None = None
    prompt_text: str | None = Field(default=None, min_length=1)


class AutomationRuntimeStatusUpdateRequest(BaseModel):
    is_active: bool


class AutomationRuntimeListResponse(BaseModel):
    generated_at: datetime
    total: int
    items: list[AutomationRuntimeItemResponse] = Field(default_factory=list)


class AutomationExecutionCreateResponse(BaseModel):
    automation_id: UUID
    analysis_request_id: UUID
    request_file_id: UUID
    execution_id: UUID
    queue_job_id: UUID
    status: ExecutionStatus
    prompt_version: int
    prompt_override_applied: bool = False


class AdminExecutionStatusResponse(BaseModel):
    execution_id: UUID
    analysis_request_id: UUID
    automation_id: UUID
    request_file_id: UUID | None = None
    request_file_name: str | None = None
    prompt_override_applied: bool = False
    status: ExecutionStatus
    progress: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    checked_at: datetime
