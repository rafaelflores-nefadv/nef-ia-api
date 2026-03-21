from __future__ import annotations

import base64
import hashlib
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.services.execution_service import ExecutionService
from app.services.execution_engine import EngineExecutionInput, INPUT_ROLE_PRIMARY


@dataclass(slots=True)
class PromptTestEngineResult:
    status: str
    provider_id: str
    provider_slug: str
    model_id: str
    model_slug: str
    credential_id: str | None
    credential_name: str
    prompt_override_applied: bool
    result_type: str
    output_text: str | None
    output_file_name: str | None
    output_file_mime_type: str | None
    output_file_base64: str | None
    output_file_checksum: str | None
    output_file_size: int
    provider_calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost: Decimal
    duration_ms: int
    processing_summary: dict[str, Any]


class PromptTestEngineService:
    def __init__(
        self,
        *,
        operational_session: Session,
        shared_session: Session,
    ) -> None:
        self.execution_service = ExecutionService(
            operational_session=operational_session,
            shared_session=shared_session,
        )

    def execute(
        self,
        *,
        provider_id: str,
        model_id: str,
        credential_id: str | None,
        prompt_override: str,
        upload_file: UploadFile,
    ) -> PromptTestEngineResult:
        prompt_text = str(prompt_override or "").strip()
        if not prompt_text:
            raise AppException(
                "Prompt override is required for prompt test execution.",
                status_code=422,
                code="invalid_prompt_override",
            )

        self.execution_service.file_service._validate_upload_file(upload_file)
        file_name = str(upload_file.filename or "").strip()
        if not file_name:
            raise AppException(
                "File name is required.",
                status_code=400,
                code="missing_file_name",
            )

        file_content = upload_file.file.read()
        if not isinstance(file_content, (bytes, bytearray)) or len(file_content) <= 0:
            raise AppException(
                "Uploaded file is empty.",
                status_code=400,
                code="empty_uploaded_file",
            )

        runtime = self.execution_service.provider_service.resolve_runtime(
            provider_slug=provider_id,
            model_slug=model_id,
            credential_id=self.execution_service.provider_service._coerce_uuid(credential_id),
        )
        execution_profile = self.execution_service.build_direct_execution_profile()
        execution_id = uuid4()
        file_suffix = Path(file_name).suffix or ".bin"
        temp_path: Path | None = None
        original_usage_service = self.execution_service.usage_service
        started_at = perf_counter()

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_suffix) as temp_file:
                temp_file.write(bytes(file_content))
                temp_file.flush()
                temp_path = Path(temp_file.name)

            execution_input = EngineExecutionInput(
                request_file_id=uuid4(),
                role=INPUT_ROLE_PRIMARY,
                order_index=0,
                file_name=file_name,
                file_path=str(temp_path),
                mime_type=str(upload_file.content_type or "").strip() or None,
                file_kind=self.execution_service.strategy_engine.detect_file_kind(
                    file_name=file_name,
                    mime_type=str(upload_file.content_type or "").strip() or None,
                ),
                source="prompt_test_direct",
            )
            processing_plan = self.execution_service._resolve_processing_strategy(
                processing_inputs=[execution_input]
            )

            self.execution_service.usage_service = SimpleNamespace(register_usage=lambda **_: None)
            processed_output = self.execution_service._process_execution_by_strategy(
                execution_id=execution_id,
                processing_plan=processing_plan,
                official_prompt=prompt_text,
                runtime=runtime,
                execution_started_at=started_at,
                execution_profile=execution_profile,
            )
        finally:
            self.execution_service.usage_service = original_usage_service
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

        duration_ms = max(int((perf_counter() - started_at) * 1000), 0)
        mime_type = str(processed_output.mime_type or "application/octet-stream")
        file_extension = Path(str(processed_output.file_name or "")).suffix.lower()
        result_type = "file" if file_extension in {".xlsx", ".csv"} else "text"
        output_text: str | None = None
        output_file_base64: str | None = None
        output_file_checksum: str | None = None
        output_file_size = len(processed_output.content)

        if result_type == "text":
            output_text = processed_output.content.decode("utf-8", errors="replace")
        else:
            output_file_base64 = base64.b64encode(processed_output.content).decode("ascii")
            output_file_checksum = hashlib.sha256(processed_output.content).hexdigest()

        return PromptTestEngineResult(
            status="completed",
            provider_id=str(runtime.provider.id),
            provider_slug=runtime.provider.slug,
            model_id=str(runtime.model.id),
            model_slug=runtime.model.model_slug,
            credential_id=str(runtime.credential.id) if runtime.credential is not None else None,
            credential_name=str(runtime.credential.credential_name or ""),
            prompt_override_applied=True,
            result_type=result_type,
            output_text=output_text,
            output_file_name=processed_output.file_name,
            output_file_mime_type=mime_type,
            output_file_base64=output_file_base64,
            output_file_checksum=output_file_checksum,
            output_file_size=output_file_size,
            provider_calls=processed_output.provider_calls,
            input_tokens=processed_output.total_input_tokens,
            output_tokens=processed_output.total_output_tokens,
            estimated_cost=processed_output.total_cost,
            duration_ms=duration_ms,
            processing_summary=processed_output.processing_summary,
        )
