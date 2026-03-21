from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.constants import ExecutionStatus


class AutomationRuntimeItemResponse(BaseModel):
    automation_id: UUID
    automation_name: str
    automation_slug: str | None = None
    automation_is_active: bool
    is_test_automation: bool = False
    prompt_available: bool
    prompt_version: int | None = None
    prompt_summary: str | None = None
    provider_slug: str | None = None
    model_slug: str | None = None
    latest_analysis_request_id: UUID | None = None


class AutomationRuntimeDetailResponse(AutomationRuntimeItemResponse):
    prompt_text: str | None = None


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
