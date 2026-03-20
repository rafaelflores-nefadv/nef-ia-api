from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.constants import ExecutionStatus


class ExecutionInputFileCreateItem(BaseModel):
    request_file_id: UUID
    role: Literal["primary", "context"] | None = None
    order_index: int | None = Field(default=None, ge=0)


class ExecutionCreateRequest(BaseModel):
    analysis_request_id: UUID
    request_file_id: UUID | None = None
    request_file_ids: list[UUID] | None = None
    input_files: list[ExecutionInputFileCreateItem] | None = None

    @model_validator(mode="after")
    def validate_input_payload(self) -> "ExecutionCreateRequest":
        has_legacy = self.request_file_id is not None
        has_ids = bool(self.request_file_ids)
        has_structured = bool(self.input_files)
        if not (has_legacy or has_ids or has_structured):
            raise ValueError("Provide at least one request file via request_file_id, request_file_ids or input_files.")
        if has_ids and has_structured:
            raise ValueError("Use either request_file_ids or input_files, not both at the same time.")
        return self


class ExecutionCreateResponse(BaseModel):
    execution_id: UUID
    queue_job_id: UUID
    status: ExecutionStatus


class ExecutionStatusResponse(BaseModel):
    execution_id: UUID
    status: ExecutionStatus
    progress: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime


class ExecutionListResponse(BaseModel):
    items: list[ExecutionStatusResponse]


class ExecutionInputFileResponse(BaseModel):
    request_file_id: UUID
    file_name: str | None = None
    role: Literal["primary", "context"]
    order_index: int
    source: str


class ExecutionInputListResponse(BaseModel):
    execution_id: UUID
    items: list[ExecutionInputFileResponse]
