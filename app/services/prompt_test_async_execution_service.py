from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
import logging
import threading
from typing import Any
from uuid import UUID, uuid4

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.db.session import SessionLocal
from app.db.shared_session import SharedSessionLocal
from app.services.prompt_test_engine_service import (
    PromptTestEngineResult,
    PromptTestEngineService,
    PromptTestProgressUpdate,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PromptTestAsyncExecutionSnapshot:
    execution_id: UUID
    status: str
    phase: str
    progress_percent: int
    status_message: str
    is_terminal: bool
    error_message: str
    result_ready: bool
    result_type: str | None
    output_file_name: str | None
    output_file_mime_type: str | None
    output_file_size: int
    debug_file_name: str | None
    debug_file_mime_type: str | None
    debug_file_size: int
    processed_rows: int | None
    total_rows: int | None
    current_row: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


@dataclass(slots=True)
class _PromptTestAsyncExecutionState:
    execution_id: UUID
    status: str
    phase: str
    progress_percent: int
    status_message: str
    is_terminal: bool
    error_message: str
    result_ready: bool
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None
    result: PromptTestEngineResult | None = None
    processed_rows: int | None = None
    total_rows: int | None = None
    current_row: int | None = None


@dataclass(slots=True)
class PromptTestAsyncStartPayload:
    provider_id: str
    model_id: str
    credential_id: str | None
    prompt_override: str
    output_type: str | None
    result_parser: str | None
    result_formatter: str | None
    output_schema: dict[str, Any] | str | None
    upload_file_name: str
    upload_content: bytes
    upload_content_type: str
    debug_enabled: bool = False


class PromptTestAsyncExecutionService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[UUID, _PromptTestAsyncExecutionState] = {}
        self._retention = timedelta(hours=6)

    def start_execution(self, *, payload: PromptTestAsyncStartPayload) -> PromptTestAsyncExecutionSnapshot:
        execution_id = uuid4()
        now = datetime.now(timezone.utc)
        state = _PromptTestAsyncExecutionState(
            execution_id=execution_id,
            status="queued",
            phase="queued",
            progress_percent=2,
            status_message="Execucao de teste enfileirada.",
            is_terminal=False,
            error_message="",
            result_ready=False,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._cleanup_expired_locked(now=now)
            self._items[execution_id] = state

        worker = threading.Thread(
            target=self._run_execution,
            kwargs={"execution_id": execution_id, "payload": payload},
            daemon=True,
            name=f"prompt_test_exec_{execution_id}",
        )
        worker.start()
        return self._snapshot_from_state(state)

    def get_snapshot(self, *, execution_id: UUID) -> PromptTestAsyncExecutionSnapshot | None:
        with self._lock:
            state = self._items.get(execution_id)
            if state is None:
                return None
            return self._snapshot_from_state(state)

    def get_result(self, *, execution_id: UUID) -> PromptTestEngineResult | None:
        with self._lock:
            state = self._items.get(execution_id)
            if state is None:
                return None
            return state.result

    def _run_execution(
        self,
        *,
        execution_id: UUID,
        payload: PromptTestAsyncStartPayload,
    ) -> None:
        self._mark_running(
            execution_id=execution_id,
            phase="preparing_input",
            progress_percent=5,
            status_message="Preparando execucao de teste.",
        )
        operational_session = SessionLocal()
        shared_session = SharedSessionLocal()
        try:
            service = PromptTestEngineService(
                operational_session=operational_session,
                shared_session=shared_session,
            )
            upload = UploadFile(
                file=BytesIO(payload.upload_content),
                filename=payload.upload_file_name,
                headers=Headers({"content-type": payload.upload_content_type}),
            )
            result = service.execute(
                provider_id=payload.provider_id,
                model_id=payload.model_id,
                credential_id=payload.credential_id,
                prompt_override=payload.prompt_override,
                output_type=payload.output_type,
                result_parser=payload.result_parser,
                result_formatter=payload.result_formatter,
                output_schema=payload.output_schema,
                debug_enabled=bool(payload.debug_enabled),
                upload_file=upload,
                progress_callback=lambda update: self._apply_progress_update(
                    execution_id=execution_id,
                    update=update,
                ),
            )
            self._mark_completed(execution_id=execution_id, result=result)
        except Exception as exc:
            logger.exception(
                "Prompt-test async execution failed.",
                extra={"execution_id": str(execution_id), "phase": "prompt_test.execution.failed"},
                exc_info=exc,
            )
            self._mark_failed(
                execution_id=execution_id,
                error_message=str(exc) or "Falha inesperada na execucao de teste.",
            )
        finally:
            operational_session.close()
            shared_session.close()

    def _apply_progress_update(self, *, execution_id: UUID, update: PromptTestProgressUpdate) -> None:
        with self._lock:
            state = self._items.get(execution_id)
            if state is None or state.is_terminal:
                return

            progress_percent = self._coerce_progress(update.progress_percent)
            state.status = "running"
            state.phase = str(update.phase or "").strip().lower() or state.phase or "running_model"
            state.progress_percent = max(state.progress_percent, progress_percent)
            state.status_message = str(update.status_message or "").strip() or "Processando execucao de teste."
            state.updated_at = datetime.now(timezone.utc)

            incoming_total_rows = self._coerce_non_negative_int(update.total_rows)
            incoming_processed_rows = self._coerce_non_negative_int(update.processed_rows)
            incoming_current_row = self._coerce_non_negative_int(update.current_row)

            if incoming_total_rows is not None:
                state.total_rows = incoming_total_rows
                if state.processed_rows is not None:
                    state.processed_rows = min(state.processed_rows, incoming_total_rows)

            if incoming_processed_rows is not None:
                if state.total_rows is not None:
                    incoming_processed_rows = min(incoming_processed_rows, state.total_rows)
                state.processed_rows = incoming_processed_rows

            if incoming_current_row is not None:
                state.current_row = incoming_current_row
            elif state.processed_rows is not None and state.total_rows is not None:
                state.current_row = state.processed_rows

    def _mark_running(
        self,
        *,
        execution_id: UUID,
        phase: str,
        progress_percent: int,
        status_message: str,
    ) -> None:
        with self._lock:
            state = self._items.get(execution_id)
            if state is None:
                return
            now = datetime.now(timezone.utc)
            state.status = "running"
            state.phase = str(phase or "").strip().lower() or "running_model"
            state.progress_percent = max(state.progress_percent, self._coerce_progress(progress_percent))
            state.status_message = str(status_message or "").strip() or "Execucao em andamento."
            state.started_at = now
            state.updated_at = now
            logger.info(
                "Prompt-test async execution phase changed.",
                extra={
                    "execution_id": str(execution_id),
                    "status": state.status,
                    "phase": state.phase,
                    "progress_percent": state.progress_percent,
                    "event": "prompt_test_execution.phase_changed",
                },
            )

    def _mark_completed(self, *, execution_id: UUID, result: PromptTestEngineResult) -> None:
        with self._lock:
            state = self._items.get(execution_id)
            if state is None:
                return
            now = datetime.now(timezone.utc)
            state.status = "completed"
            state.phase = "completed"
            state.progress_percent = 100
            state.status_message = "Execucao de teste concluida. Resultado disponivel."
            state.is_terminal = True
            state.error_message = ""
            state.result_ready = True
            state.finished_at = now
            state.updated_at = now
            state.result = result
            if isinstance(result.processing_summary, dict):
                state.processed_rows = self._coerce_non_negative_int(result.processing_summary.get("processed_rows"))
                state.total_rows = self._coerce_non_negative_int(result.processing_summary.get("total_rows"))
                if state.total_rows is not None and state.processed_rows is not None:
                    state.processed_rows = min(state.processed_rows, state.total_rows)
                if state.processed_rows is not None:
                    state.current_row = state.processed_rows
            logger.info(
                "Prompt-test async execution completed.",
                extra={
                    "execution_id": str(execution_id),
                    "phase": "prompt_test.execution.completed",
                    "status": state.status,
                    "result_type": result.result_type,
                    "provider_calls": result.provider_calls,
                    "processed_rows": state.processed_rows,
                    "total_rows": state.total_rows,
                },
            )

    def _mark_failed(self, *, execution_id: UUID, error_message: str) -> None:
        with self._lock:
            state = self._items.get(execution_id)
            if state is None:
                return
            now = datetime.now(timezone.utc)
            state.status = "failed"
            state.phase = "failed"
            state.progress_percent = min(max(state.progress_percent, 1), 99)
            state.status_message = "Falha na execucao de teste."
            state.error_message = str(error_message or "").strip() or "Falha inesperada na execucao de teste."
            state.is_terminal = True
            state.result_ready = False
            state.finished_at = now
            state.updated_at = now
            logger.error(
                "Prompt-test async execution failed.",
                extra={
                    "execution_id": str(execution_id),
                    "phase": "prompt_test.execution.failed",
                    "status": state.status,
                    "progress_percent": state.progress_percent,
                    "error_message": state.error_message,
                },
            )

    @staticmethod
    def _snapshot_from_state(state: _PromptTestAsyncExecutionState) -> PromptTestAsyncExecutionSnapshot:
        result = state.result
        return PromptTestAsyncExecutionSnapshot(
            execution_id=state.execution_id,
            status=state.status,
            phase=state.phase,
            progress_percent=int(state.progress_percent),
            status_message=state.status_message,
            is_terminal=bool(state.is_terminal),
            error_message=state.error_message,
            result_ready=bool(state.result_ready),
            result_type=result.result_type if result is not None else None,
            output_file_name=result.output_file_name if result is not None else None,
            output_file_mime_type=result.output_file_mime_type if result is not None else None,
            output_file_size=int(result.output_file_size or 0) if result is not None else 0,
            debug_file_name=result.debug_file_name if result is not None else None,
            debug_file_mime_type=result.debug_file_mime_type if result is not None else None,
            debug_file_size=int(result.debug_file_size or 0) if result is not None else 0,
            processed_rows=state.processed_rows,
            total_rows=state.total_rows,
            current_row=state.current_row,
            created_at=state.created_at,
            started_at=state.started_at,
            finished_at=state.finished_at,
            updated_at=state.updated_at or state.created_at,
        )

    def _cleanup_expired_locked(self, *, now: datetime) -> None:
        expired_ids: list[UUID] = []
        for execution_id, state in self._items.items():
            if not state.is_terminal:
                continue
            reference = state.finished_at or state.updated_at or state.created_at
            if reference + self._retention < now:
                expired_ids.append(execution_id)
        for execution_id in expired_ids:
            self._items.pop(execution_id, None)

    @staticmethod
    def _coerce_progress(value: Any) -> int:
        try:
            return max(0, min(99, int(value)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _coerce_non_negative_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return None


_PROMPT_TEST_ASYNC_SERVICE = PromptTestAsyncExecutionService()


def get_prompt_test_async_execution_service() -> PromptTestAsyncExecutionService:
    return _PROMPT_TEST_ASYNC_SERVICE
