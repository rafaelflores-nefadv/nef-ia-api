from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ApiTokenPermissionInput(BaseModel):
    automation_id: UUID
    provider_id: UUID | None = None
    allow_execution: bool = True
    allow_file_upload: bool = False


class ApiTokenCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    expires_at: datetime | None = None
    permissions: list[ApiTokenPermissionInput] = Field(default_factory=list)


class ApiTokenCreateResponse(BaseModel):
    id: UUID
    name: str
    token: str
    is_active: bool
    expires_at: datetime | None
    created_at: datetime


class ApiTokenListItem(BaseModel):
    id: UUID
    name: str
    is_active: bool
    expires_at: datetime | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class ApiTokenRevokedResponse(BaseModel):
    id: UUID
    is_active: bool

