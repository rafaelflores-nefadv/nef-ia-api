from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Callable
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.integrations.storage.base import StoredFile
from app.services.execution_engine import INPUT_ROLE_PRIMARY, EngineExecutionInput
from app.services.execution_service import ExecutionProgressUpdate, ExecutionService

logger = logging.getLogger(__name__)


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
    processing_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PromptTestProgressUpdate:
    phase: str
    progress_percent: int
    status_message: str
    processed_rows: int | None = None
    total_rows: int | None = None
    current_row: int | None = None


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
        output_type: str | None = None,
        result_parser: str | None = None,
        result_formatter: str | None = None,
        output_schema: dict[str, Any] | str | None = None,
        debug_enabled: bool = False,
        progress_callback: Callable[[PromptTestProgressUpdate], None] | None = None,
    ) -> PromptTestEngineResult:
        progress_state = {"percent": 0}

        def _emit_progress(
            *,
            phase: str,
            progress_percent: int,
            status_message: str,
            processed_rows: int | None = None,
            total_rows: int | None = None,
            current_row: int | None = None,
        ) -> None:
            normalized_percent = max(progress_state["percent"], min(int(progress_percent), 99))
            progress_state["percent"] = normalized_percent
            self._notify_progress(
                progress_callback=progress_callback,
                phase=phase,
                progress_percent=normalized_percent,
                status_message=status_message,
                processed_rows=processed_rows,
                total_rows=total_rows,
                current_row=current_row,
            )

        def _handle_pipeline_progress(update: ExecutionProgressUpdate) -> None:
            phase = str(update.phase or "").strip().lower()
            status_message = str(update.status_message or "").strip()
            processed_rows = self._safe_int(update.processed_rows)
            total_rows = self._safe_int(update.total_rows)
            current_row = self._safe_int(update.current_row)
            processed_chunks = self._safe_int(update.processed_chunks)
            total_chunks = self._safe_int(update.total_chunks)

            if phase == "processing_rows":
                normalized_total_rows = max(int(total_rows or 0), 0)
                normalized_processed_rows = max(int(processed_rows or 0), 0)
                if normalized_total_rows > 0:
                    normalized_processed_rows = min(normalized_processed_rows, normalized_total_rows)
                    progress_percent = 10 + int((normalized_processed_rows / normalized_total_rows) * 75)
                else:
                    progress_percent = max(progress_state["percent"], 12)
                _emit_progress(
                    phase="processing_rows",
                    progress_percent=progress_percent,
                    status_message=status_message or "Processando linhas no modelo de IA.",
                    processed_rows=normalized_processed_rows,
                    total_rows=normalized_total_rows if normalized_total_rows > 0 else None,
                    current_row=current_row,
                )
                return

            if phase == "processing_chunks":
                normalized_total_chunks = max(int(total_chunks or 0), 0)
                normalized_processed_chunks = max(int(processed_chunks or 0), 0)
                if normalized_total_chunks > 0:
                    normalized_processed_chunks = min(normalized_processed_chunks, normalized_total_chunks)
                    progress_percent = 10 + int((normalized_processed_chunks / normalized_total_chunks) * 75)
                else:
                    progress_percent = max(progress_state["percent"], 12)
                _emit_progress(
                    phase="running_model",
                    progress_percent=progress_percent,
                    status_message=status_message or "Executando processamento no modelo de IA.",
                )
                return

            if phase == "normalizing_output":
                _emit_progress(
                    phase="normalizing_output",
                    progress_percent=max(progress_state["percent"], 88),
                    status_message=status_message or "Normalizando saida conforme contrato.",
                    processed_rows=processed_rows,
                    total_rows=total_rows,
                )
                return

            if phase == "exporting_result":
                _emit_progress(
                    phase="exporting_result",
                    progress_percent=max(progress_state["percent"], 95),
                    status_message=status_message or "Gerando arquivo final da execucao.",
                    processed_rows=processed_rows,
                    total_rows=total_rows,
                )
                return

            if phase in {"reading_input", "prompt_build"}:
                _emit_progress(
                    phase="preparing_input",
                    progress_percent=max(progress_state["percent"], 10),
                    status_message=status_message or "Preparando dados para execucao.",
                )

        _emit_progress(
            phase="preparing_input",
            progress_percent=3,
            status_message="Preparando execucao de teste.",
        )
        prompt_text = str(prompt_override or "").strip()
        if not prompt_text:
            raise AppException(
                "Prompt override is required for prompt test execution.",
                status_code=422,
                code="invalid_prompt_override",
            )

        file_name = str(upload_file.filename or "").strip()
        if not file_name:
            raise AppException(
                "File name is required.",
                status_code=400,
                code="missing_file_name",
            )
        _emit_progress(
            phase="validating_file",
            progress_percent=7,
            status_message="Validando arquivo de entrada.",
        )
        self.execution_service.file_service._validate_upload_file(upload_file)

        _emit_progress(
            phase="preparing_input",
            progress_percent=10,
            status_message="Preparando runtime e estrategia de execucao.",
        )
        runtime = self.execution_service.provider_service.resolve_runtime(
            provider_slug=provider_id,
            model_slug=model_id,
            credential_id=self.execution_service.provider_service._coerce_uuid(credential_id),
        )
        execution_profile = self.execution_service.build_direct_execution_profile()
        execution_id = uuid4()
        stored_input_file: StoredFile | None = None
        original_usage_service = self.execution_service.usage_service
        started_at = perf_counter()

        try:
            try:
                stored_input_file = self.execution_service.file_service.storage.save_uploaded_file(
                    upload_file=upload_file,
                    category="prompt-tests",
                    entity_id=execution_id,
                    max_size_bytes=self.execution_service.file_service.max_size_bytes,
                )
            except ValueError as exc:
                raise AppException(
                    "Uploaded file exceeds configured maximum size.",
                    status_code=413,
                    code="file_too_large",
                ) from exc

            if stored_input_file.file_size <= 0:
                self._delete_stored_input_file_safely(stored_input_file)
                stored_input_file = None
                raise AppException(
                    "Uploaded file is empty.",
                    status_code=400,
                    code="empty_uploaded_file",
                )
            _emit_progress(
                phase="preparing_input",
                progress_percent=12,
                status_message="Arquivo recebido. Montando plano de processamento.",
            )

            execution_input = EngineExecutionInput(
                request_file_id=uuid4(),
                role=INPUT_ROLE_PRIMARY,
                order_index=0,
                file_name=stored_input_file.file_name,
                file_path=stored_input_file.relative_path,
                mime_type=stored_input_file.mime_type,
                file_kind=self.execution_service.strategy_engine.detect_file_kind(
                    file_name=stored_input_file.file_name,
                    mime_type=stored_input_file.mime_type,
                ),
                source="prompt_test_direct",
            )
            processing_plan = self.execution_service._resolve_processing_strategy(processing_inputs=[execution_input])
            resolved_output_contract = self.execution_service._resolve_execution_output_contract(
                automation_id=None,
                automation_slug=None,
                processing_plan=processing_plan,
                runtime_output_type=str(output_type or "").strip() or None,
                runtime_result_parser=str(result_parser or "").strip() or None,
                runtime_result_formatter=str(result_formatter or "").strip() or None,
                runtime_output_schema=output_schema,
            )
            processing_plan = self.execution_service._resolve_processing_strategy(
                processing_inputs=[execution_input],
                output_contract=resolved_output_contract,
            )

            self.execution_service.usage_service = SimpleNamespace(register_usage=lambda **_: None)
            processed_output = self.execution_service._process_execution_by_strategy(
                execution_id=execution_id,
                processing_plan=processing_plan,
                official_prompt=prompt_text,
                runtime=runtime,
                execution_started_at=started_at,
                execution_profile=execution_profile,
                debug_enabled=bool(debug_enabled),
                progress_callback=_handle_pipeline_progress,
            )
            summary = processed_output.processing_summary if isinstance(processed_output.processing_summary, dict) else {}
            _emit_progress(
                phase="normalizing_output",
                progress_percent=90,
                status_message="Normalizando saida conforme contrato.",
                processed_rows=self._safe_int(summary.get("processed_rows")),
                total_rows=self._safe_int(summary.get("total_rows")),
            )
        finally:
            self.execution_service.usage_service = original_usage_service
            if stored_input_file is not None:
                self._delete_stored_input_file_safely(stored_input_file)

        duration_ms = max(int((perf_counter() - started_at) * 1000), 0)
        mime_type = str(processed_output.mime_type or "application/octet-stream")
        file_extension = Path(str(processed_output.file_name or "")).suffix.lower()
        result_type = "file" if file_extension in {".xlsx", ".csv"} else "text"
        output_text: str | None = None
        output_file_base64: str | None = None
        output_file_checksum: str | None = None
        output_file_size = len(processed_output.content)
        debug_file_name: str | None = None
        debug_file_mime_type: str | None = None
        debug_file_base64: str | None = None
        debug_file_checksum: str | None = None
        debug_file_size = 0
        _emit_progress(
            phase="exporting_result",
            progress_percent=97,
            status_message="Exportando resultado final.",
            processed_rows=self._safe_int(processed_output.processing_summary.get("processed_rows"))
            if isinstance(processed_output.processing_summary, dict)
            else None,
            total_rows=self._safe_int(processed_output.processing_summary.get("total_rows"))
            if isinstance(processed_output.processing_summary, dict)
            else None,
        )

        if result_type == "text":
            output_text = processed_output.content.decode("utf-8", errors="replace")
        else:
            output_file_base64 = base64.b64encode(processed_output.content).decode("ascii")
            output_file_checksum = hashlib.sha256(processed_output.content).hexdigest()
        debug_file = next(
            (
                item
                for item in (getattr(processed_output, "auxiliary_files", None) or [])
                if str(getattr(item, "file_type", "") or "") == "debug"
            ),
            None,
        )
        if debug_file is not None:
            debug_file_name = str(debug_file.file_name or "").strip() or f"debug_{execution_id}.bin"
            debug_file_mime_type = str(debug_file.mime_type or "").strip() or "application/octet-stream"
            debug_file_size = len(debug_file.content or b"")
            if debug_file_size > 0:
                debug_file_base64 = base64.b64encode(debug_file.content).decode("ascii")
                debug_file_checksum = hashlib.sha256(debug_file.content).hexdigest()

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
            debug_file_name=debug_file_name,
            debug_file_mime_type=debug_file_mime_type,
            debug_file_base64=debug_file_base64,
            debug_file_checksum=debug_file_checksum,
            debug_file_size=debug_file_size,
            provider_calls=processed_output.provider_calls,
            input_tokens=processed_output.total_input_tokens,
            output_tokens=processed_output.total_output_tokens,
            estimated_cost=processed_output.total_cost,
            duration_ms=duration_ms,
            processing_summary=processed_output.processing_summary,
        )

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _notify_progress(
        *,
        progress_callback: Callable[[PromptTestProgressUpdate], None] | None,
        phase: str,
        progress_percent: int,
        status_message: str,
        processed_rows: int | None = None,
        total_rows: int | None = None,
        current_row: int | None = None,
    ) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(
                PromptTestProgressUpdate(
                    phase=str(phase or "").strip().lower() or "running_model",
                    progress_percent=max(0, min(100, int(progress_percent))),
                    status_message=str(status_message or "").strip() or "Processando execucao de teste.",
                    processed_rows=processed_rows,
                    total_rows=total_rows,
                    current_row=current_row,
                )
            )
        except Exception:
            logger.warning("Prompt-test progress callback failed.", exc_info=True)

    def _delete_stored_input_file_safely(self, stored_file: StoredFile) -> None:
        try:
            self.execution_service.file_service.storage.delete_file(stored_file.relative_path)
        except Exception:
            logger.warning(
                "Failed to delete prompt test temporary file from storage.",
                extra={"relative_path": stored_file.relative_path},
                exc_info=True,
            )
