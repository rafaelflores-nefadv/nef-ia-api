from decimal import Decimal
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PromptTestExecutionStartResponse(BaseModel):
    execution_id: UUID
    status: str
    phase: str
    progress_percent: int = 0
    status_message: str
    is_terminal: bool = False
    created_at: datetime


class PromptTestExecutionStatusResponse(BaseModel):
    execution_id: UUID
    status: str
    phase: str
    progress_percent: int = 0
    status_message: str
    is_terminal: bool = False
    error_message: str = ""
    result_ready: bool = False
    result_type: str | None = None
    output_file_name: str | None = None
    output_file_mime_type: str | None = None
    output_file_size: int = 0
    debug_file_name: str | None = None
    debug_file_mime_type: str | None = None
    debug_file_size: int = 0
    processed_rows: int | None = None
    total_rows: int | None = None
    current_row: int | None = None
    result_url: str | None = None
    download_url: str | None = None
    debug_download_url: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime


class PromptTestDirectExecutionResponse(BaseModel):
    status: str
    provider_id: UUID
    provider_slug: str
    model_id: UUID
    model_slug: str
    credential_id: UUID | None = None
    credential_name: str = ""
    prompt_override_applied: bool = True
    result_type: str
    output_text: str | None = None
    output_file_name: str | None = None
    output_file_mime_type: str | None = None
    output_file_base64: str | None = None
    output_file_checksum: str | None = None
    output_file_size: int = 0
    debug_file_name: str | None = None
    debug_file_mime_type: str | None = None
    debug_file_base64: str | None = None
    debug_file_checksum: str | None = None
    debug_file_size: int = 0
    provider_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: Decimal = Decimal("0")
    duration_ms: int = 0
    processing_summary: dict[str, Any] = Field(default_factory=dict)


class PromptTestExecutionResultResponse(PromptTestDirectExecutionResponse):
    execution_id: UUID


class PromptTestCopyToOfficialRequest(BaseModel):
    owner_token_id: UUID
    name: str = Field(min_length=1, max_length=255)
    provider_id: UUID
    model_id: UUID
    credential_id: UUID | None = None
    output_type: str | None = Field(default=None, min_length=1, max_length=64)
    result_parser: str | None = Field(default=None, min_length=1, max_length=64)
    result_formatter: str | None = Field(default=None, min_length=1, max_length=64)
    output_schema: dict[str, Any] | None = None
    is_active: bool = True
    prompt_text: str = Field(min_length=1)
    source_test_automation_id: UUID | None = None
    source_test_prompt_id: int | None = None


class PromptTestCopyToOfficialResponse(BaseModel):
    owner_token_id: UUID
    automation_id: UUID
    automation_name: str
    prompt_id: UUID
    prompt_version: int
    source_test_automation_id: UUID | None = None
    source_test_prompt_id: int | None = None
