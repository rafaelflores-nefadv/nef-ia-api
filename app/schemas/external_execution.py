from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.constants import ExecutionStatus

class _BaseExternalExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_data: dict | list | str | int | float | bool | None = None


class ExternalExecutePromptRequest(_BaseExternalExecuteRequest):
    pass


class ExternalExecuteAutomationRequest(_BaseExternalExecuteRequest):
    pass


class ExternalExecutionResponse(BaseModel):
    id: UUID
    status: ExecutionStatus
    resource_type: Literal["prompt", "automation"]
    resource_id: UUID
    automation_id: UUID
    prompt_id: UUID | None = None
    analysis_request_id: UUID
    queue_job_id: UUID | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    has_files: bool | None = None
    has_structured_result: bool | None = None


class ExternalExecutionListResponse(BaseModel):
    items: list[ExternalExecutionResponse]


class ExternalExecutionFileResponse(BaseModel):
    file_id: UUID
    execution_id: UUID
    logical_type: Literal["input", "output"]
    file_type: str
    file_name: str
    file_size: int
    mime_type: str | None = None
    checksum: str | None = None
    created_at: datetime | None = None


class ExternalExecutionFileListResponse(BaseModel):
    items: list[ExternalExecutionFileResponse]


class ExternalExecutionResultResponse(BaseModel):
    execution_id: UUID
    result: Any | None = None
    source_file_id: UUID | None = None
    source_mime_type: str | None = None
