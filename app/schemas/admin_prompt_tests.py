from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PromptTestCreateResponse(BaseModel):
    id: UUID
    status: str
    prompt_title: str
    provider_slug: str
    model_slug: str
    file_name: str
    created_at: datetime


class PromptTestStatusResponse(BaseModel):
    id: UUID
    status: str
    prompt_title: str
    provider_slug: str
    model_slug: str
    file_name: str
    file_size: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    output_text: str | None = None


class PromptTestRuntimeConfigureRequest(BaseModel):
    name: str = Field(min_length=3, max_length=180)
    provider_id: UUID
    model_id: UUID


class PromptTestRuntimeResponse(BaseModel):
    automation_id: UUID
    automation_name: str
    automation_slug: str | None = None
    analysis_request_id: UUID
    provider_slug: str
    model_slug: str
    is_test_automation: bool = True
