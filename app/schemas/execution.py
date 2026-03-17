from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.core.constants import ExecutionStatus


class ExecutionCreateRequest(BaseModel):
    analysis_request_id: UUID
    request_file_id: UUID


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
