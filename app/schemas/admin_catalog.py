from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProviderCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True


class ProviderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    slug: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class ProviderResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProviderModelCreateRequest(BaseModel):
    model_name: str = Field(min_length=2, max_length=120)
    model_slug: str = Field(min_length=2, max_length=120)
    context_limit: int = Field(default=8192, ge=1)
    cost_input_per_1k_tokens: Decimal = Field(default=Decimal("0"))
    cost_output_per_1k_tokens: Decimal = Field(default=Decimal("0"))
    is_active: bool = True


class ProviderModelUpdateRequest(BaseModel):
    model_name: str | None = Field(default=None, min_length=2, max_length=120)
    model_slug: str | None = Field(default=None, min_length=2, max_length=120)
    context_limit: int | None = Field(default=None, ge=1)
    cost_input_per_1k_tokens: Decimal | None = Field(default=None)
    cost_output_per_1k_tokens: Decimal | None = Field(default=None)
    is_active: bool | None = None


class ProviderModelResponse(BaseModel):
    id: UUID
    provider_id: UUID
    model_name: str
    model_slug: str
    context_limit: int
    cost_input_per_1k_tokens: Decimal
    cost_output_per_1k_tokens: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AvailableProviderModelResponse(BaseModel):
    provider_id: UUID
    provider_slug: str
    provider_model_id: str
    model_name: str
    model_slug: str
    context_limit: int | None = None
    cost_input_per_1k_tokens: Decimal | None = None
    cost_output_per_1k_tokens: Decimal | None = None
    description: str | None = None
    is_registered: bool = False


class ProviderCredentialCreateRequest(BaseModel):
    credential_name: str = Field(min_length=2, max_length=120)
    api_key: str = Field(min_length=4, max_length=2000)
    config_json: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class ProviderCredentialUpdateRequest(BaseModel):
    credential_name: str | None = Field(default=None, min_length=2, max_length=120)
    api_key: str | None = Field(default=None, min_length=4, max_length=2000)
    config_json: dict[str, Any] | None = None
    is_active: bool | None = None


class ProviderCredentialResponse(BaseModel):
    id: UUID
    provider_id: UUID
    credential_name: str
    config_json: dict[str, Any]
    is_active: bool
    secret_masked: str
    created_at: datetime
    updated_at: datetime


class CatalogProviderStatus(BaseModel):
    provider_id: UUID
    name: str
    slug: str
    is_active: bool
    total_models: int
    active_models: int
    total_credentials: int
    active_credentials: int
    has_operational_credential: bool
    operational_ready: bool
    inconsistencies: list[str]


class CatalogStatusResponse(BaseModel):
    generated_at: datetime
    providers: list[CatalogProviderStatus]
    global_inconsistencies: list[str]
