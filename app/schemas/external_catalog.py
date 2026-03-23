from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AutomationCreateRequest(_StrictRequestModel):
    name: str = Field(min_length=1, max_length=255)
    provider_id: UUID
    model_id: UUID
    credential_id: UUID | None = None
    output_type: str | None = Field(default=None, min_length=1, max_length=64)
    result_parser: str | None = Field(default=None, min_length=1, max_length=64)
    result_formatter: str | None = Field(default=None, min_length=1, max_length=64)
    output_schema: dict[str, Any] | None = None
    is_active: bool = True


class AutomationSummaryResponse(BaseModel):
    id: UUID
    name: str
    is_active: bool


class AutomationResponse(AutomationSummaryResponse):
    provider_id: UUID | None = None
    model_id: UUID | None = None
    credential_id: UUID | None = None
    output_type: str | None = None
    result_parser: str | None = None
    result_formatter: str | None = None
    output_schema: dict[str, Any] | None = None


class AutomationListResponse(BaseModel):
    items: list[AutomationSummaryResponse]


class AutomationPromptCreateRequest(_StrictRequestModel):
    automation_id: UUID
    prompt_text: str = Field(min_length=1)


class AutomationUpdateRequest(_StrictRequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider_id: UUID | None = None
    model_id: UUID | None = None
    credential_id: UUID | None = None
    output_type: str | None = Field(default=None, min_length=1, max_length=64)
    result_parser: str | None = Field(default=None, min_length=1, max_length=64)
    result_formatter: str | None = Field(default=None, min_length=1, max_length=64)
    output_schema: dict[str, Any] | None = None
    is_active: bool | None = None


class PromptUpdateRequest(_StrictRequestModel):
    automation_id: UUID | None = None
    prompt_text: str | None = Field(default=None, min_length=1)


class StatusUpdateRequest(_StrictRequestModel):
    is_active: bool


class AutomationPromptResponse(BaseModel):
    id: UUID
    automation_id: UUID
    prompt_text: str
    version: int
    created_at: datetime
    is_active: bool


class AutomationPromptListResponse(BaseModel):
    items: list[AutomationPromptResponse]


class ExternalProviderResponse(BaseModel):
    id: UUID
    name: str
    slug: str | None = None
    is_active: bool


class ExternalProviderModelResponse(BaseModel):
    id: UUID
    provider_id: UUID
    name: str
    slug: str | None = None
    is_active: bool


class ExternalCredentialResponse(BaseModel):
    id: UUID
    provider_id: UUID
    name: str
    is_active: bool


class ExternalProviderListResponse(BaseModel):
    items: list[ExternalProviderResponse]


class ExternalProviderModelListResponse(BaseModel):
    items: list[ExternalProviderModelResponse]


class ExternalCredentialListResponse(BaseModel):
    items: list[ExternalCredentialResponse]
