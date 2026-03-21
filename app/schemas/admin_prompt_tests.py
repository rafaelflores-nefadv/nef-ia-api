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


class PromptTestAutomationUpdateRequest(PromptTestRuntimeConfigureRequest):
    is_active: bool = True


class PromptTestTechnicalRuntimeResponse(BaseModel):
    technical_automation_id: UUID
    technical_automation_name: str
    technical_automation_slug: str | None = None
    shared_automation_id: UUID
    analysis_request_id: UUID
    is_test_automation: bool = True


class PromptTestAutomationResponse(BaseModel):
    automation_id: UUID
    automation_name: str
    automation_slug: str | None = None
    provider_id: UUID | None = None
    model_id: UUID | None = None
    provider_slug: str
    model_slug: str
    is_active: bool = True
    is_test_automation: bool = True


class PromptTestAutomationListResponse(BaseModel):
    total: int
    items: list[PromptTestAutomationResponse] = Field(default_factory=list)
