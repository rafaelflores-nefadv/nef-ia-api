from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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
