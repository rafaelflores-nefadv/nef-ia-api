from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

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
    provider_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: Decimal = Decimal("0")
    duration_ms: int = 0
    processing_summary: dict[str, Any] = Field(default_factory=dict)
