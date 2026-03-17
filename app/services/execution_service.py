import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import ExecutionStatus
from app.core.exceptions import AppException
from app.core.log_context import bind_log_context, reset_log_context
from app.integrations.providers.base import ProviderExecutionResult
from app.integrations.queue.dispatcher import enqueue_execution_job
from app.models.operational import (
    DjangoAiApiToken,
    DjangoAiApiTokenPermission,
    DjangoAiAuditLog,
    DjangoAiQueueJob,
)
from app.repositories.operational import AuditLogRepository, QueueJobRepository, RequestFileRepository
from app.repositories.shared import SharedAnalysisRepository, SharedExecutionRepository
from app.services.file_service import FileService
from app.services.provider_service import ProviderRuntimeSelection, ProviderService
from app.services.shared.automation_runtime_resolver import AutomationRuntimeResolverService
from app.services.token_service import check_token_permission
from app.services.usage_service import UsageService

settings = get_settings()
logger = logging.getLogger(__name__)

RETRYABLE_PROVIDER_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
RETRYABLE_ERROR_CODES = {"provider_timeout", "provider_network_error"}


@dataclass(slots=True)
class ExecutionCreateResult:
    execution_id: UUID
    queue_job_id: UUID
    status: ExecutionStatus


@dataclass(slots=True)
class ExecutionStatusResult:
    execution_id: UUID
    status: ExecutionStatus
    progress: int | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime


class ExecutionService:
    def __init__(
        self,
        *,
        operational_session: Session,
        shared_session: Session,
    ) -> None:
        self.operational_session = operational_session
        self.shared_session = shared_session
        self.request_files = RequestFileRepository(operational_session)
        self.queue_jobs = QueueJobRepository(operational_session)
        self.audit_logs = AuditLogRepository(operational_session)
        self.shared_analysis = SharedAnalysisRepository(shared_session)
        self.shared_executions = SharedExecutionRepository(shared_session)
        self.runtime_resolver = AutomationRuntimeResolverService(shared_session)
        self.provider_service = ProviderService(operational_session)
        self.usage_service = UsageService(operational_session)
        self.file_service = FileService(
            operational_session=operational_session,
            shared_session=shared_session,
        )

    def create_execution(
        self,
        *,
        analysis_request_id: UUID,
        request_file_id: UUID,
        api_token: DjangoAiApiToken,
        token_permissions: list[DjangoAiApiTokenPermission],
        ip_address: str | None = None,
        correlation_id: str | None = None,
    ) -> ExecutionCreateResult:
        analysis_request = self.shared_analysis.get_request_by_id(analysis_request_id)
        if analysis_request is None:
            raise AppException(
                "analysis_request_id not found in shared system.",
                status_code=404,
                code="analysis_request_not_found",
                details={"analysis_request_id": str(analysis_request_id)},
            )

        allowed = check_token_permission(
            permissions=token_permissions,
            operation="execution",
            automation_id=analysis_request.automation_id,
        )
        if not allowed:
            raise AppException(
                "Token does not allow execution for this automation.",
                status_code=403,
                code="execution_permission_denied",
            )

        request_file = self.request_files.get_by_id(request_file_id)
        if request_file is None:
            raise AppException(
                "Request file not found.",
                status_code=404,
                code="request_file_not_found",
                details={"request_file_id": str(request_file_id)},
            )
        if request_file.analysis_request_id != analysis_request_id:
            raise AppException(
                "request_file_id does not belong to analysis_request_id.",
                status_code=409,
                code="request_file_analysis_mismatch",
            )

        execution = self.shared_executions.create(
            analysis_request_id=analysis_request_id,
            status=ExecutionStatus.PENDING.value,
        )
        self.shared_session.commit()

        queue_job = DjangoAiQueueJob(
            execution_id=execution.id,
            request_file_id=request_file.id,
            job_status=ExecutionStatus.QUEUED.value,
            retry_count=0,
        )
        self.queue_jobs.add(queue_job)
        self.audit_logs.add(
            DjangoAiAuditLog(
                action_type="execution_created",
                entity_type="analysis_executions",
                entity_id=str(execution.id),
                performed_by_user_id=None,
                changes_json={
                    "analysis_request_id": str(analysis_request_id),
                    "request_file_id": str(request_file_id),
                    "token_id": str(api_token.id),
                    "queue_job_id": str(queue_job.id),
                },
                ip_address=ip_address,
            )
        )
        self.operational_session.commit()

        self.shared_executions.update_status(execution_id=execution.id, status=ExecutionStatus.QUEUED.value)
        self.shared_session.commit()

        try:
            enqueue_execution_job(
                execution_id=execution.id,
                queue_job_id=queue_job.id,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            logger.exception("Failed to enqueue execution job.", extra={"execution_id": str(execution.id)}, exc_info=exc)
            self._mark_execution_failed(
                execution_id=execution.id,
                queue_job_id=queue_job.id,
                error_message="Failed to enqueue execution job.",
                worker_name="api",
                ip_address=ip_address,
                register_error_file=False,
            )
            raise AppException(
                "Failed to enqueue execution job.",
                status_code=500,
                code="queue_enqueue_failed",
            ) from exc

        logger.info(
            "Execution created and queued.",
            extra={
                "execution_id": str(execution.id),
                "analysis_request_id": str(analysis_request_id),
                "request_file_id": str(request_file_id),
                "queue_job_id": str(queue_job.id),
            },
        )
        return ExecutionCreateResult(
            execution_id=execution.id,
            queue_job_id=queue_job.id,
            status=ExecutionStatus.QUEUED,
        )

    def get_execution_status(
        self,
        *,
        execution_id: UUID,
        token_permissions: list[DjangoAiApiTokenPermission],
    ) -> ExecutionStatusResult:
        execution = self.shared_executions.get_by_id(execution_id)
        if execution is None:
            raise AppException("Execution not found.", status_code=404, code="execution_not_found")

        analysis_request = self.shared_analysis.get_request_by_id(execution.analysis_request_id)
        if analysis_request is None:
            raise AppException("Related analysis request not found.", status_code=404, code="analysis_request_not_found")

        allowed = check_token_permission(
            permissions=token_permissions,
            operation="execution",
            automation_id=analysis_request.automation_id,
        )
        if not allowed:
            raise AppException("Token cannot access this execution.", status_code=403, code="execution_permission_denied")

        latest_job = self.queue_jobs.get_latest_by_execution_id(execution.id)
        return ExecutionStatusResult(
            execution_id=execution.id,
            status=self._parse_status(execution.status),
            progress=None,
            started_at=latest_job.started_at if latest_job else None,
            finished_at=latest_job.finished_at if latest_job else None,
            error_message=latest_job.error_message if latest_job else None,
            created_at=execution.created_at,
        )

    def list_executions_for_analysis_request(
        self,
        *,
        analysis_request_id: UUID,
        token_permissions: list[DjangoAiApiTokenPermission],
    ) -> list[ExecutionStatusResult]:
        analysis_request = self.shared_analysis.get_request_by_id(analysis_request_id)
        if analysis_request is None:
            raise AppException("analysis_request_id not found.", status_code=404, code="analysis_request_not_found")

        allowed = check_token_permission(
            permissions=token_permissions,
            operation="execution",
            automation_id=analysis_request.automation_id,
        )
        if not allowed:
            raise AppException("Token cannot list executions for this request.", status_code=403, code="execution_permission_denied")

        executions = self.shared_executions.list_by_analysis_request_id(analysis_request_id)
        items: list[ExecutionStatusResult] = []
        for execution in executions:
            latest_job = self.queue_jobs.get_latest_by_execution_id(execution.id)
            items.append(
                ExecutionStatusResult(
                    execution_id=execution.id,
                    status=self._parse_status(execution.status),
                    progress=None,
                    started_at=latest_job.started_at if latest_job else None,
                    finished_at=latest_job.finished_at if latest_job else None,
                    error_message=latest_job.error_message if latest_job else None,
                    created_at=execution.created_at,
                )
            )
        return items

    def process_execution_job(
        self,
        *,
        execution_id: UUID,
        queue_job_id: UUID,
        worker_name: str,
        correlation_id: str | None = None,
    ) -> None:
        queue_job = self.queue_jobs.get_by_id(queue_job_id)
        if queue_job is None:
            raise AppException("Queue job not found.", status_code=404, code="queue_job_not_found")
        if queue_job.execution_id != execution_id:
            raise AppException(
                "queue_job_id does not match execution_id.",
                status_code=409,
                code="queue_job_execution_mismatch",
            )
        if queue_job.request_file_id is None:
            raise AppException("Queue job is missing request_file_id.", status_code=409, code="queue_job_request_file_missing")

        shared_execution = self.shared_executions.get_by_id(execution_id)
        if shared_execution is None:
            raise AppException("Execution not found.", status_code=404, code="execution_not_found")

        if shared_execution.status == ExecutionStatus.COMPLETED.value:
            logger.info("Execution already completed. Skipping duplicate worker run.", extra={"execution_id": str(execution_id)})
            return

        if self._is_concurrency_limited(queue_job_id=queue_job_id):
            self._schedule_retry(
                execution_id=execution_id,
                queue_job=queue_job,
                reason="Global concurrency limit reached.",
                worker_name=worker_name,
                correlation_id=correlation_id,
            )
            return

        acquired = self.queue_jobs.acquire_for_processing(
            queue_job_id=queue_job_id,
            worker_name=worker_name,
            started_at=datetime.now(timezone.utc),
        )
        self.operational_session.commit()
        if not acquired:
            logger.info(
                "Queue job was already acquired by another worker. Skipping duplicate run.",
                extra={"execution_id": str(execution_id), "queue_job_id": str(queue_job_id)},
            )
            return

        queue_job = self.queue_jobs.get_by_id(queue_job_id)
        if queue_job is None:
            return

        try:
            self.shared_executions.update_status(execution_id=execution_id, status=ExecutionStatus.PROCESSING.value)
            self.shared_session.commit()
            self.audit_logs.add(
                DjangoAiAuditLog(
                    action_type="execution_started",
                    entity_type="analysis_executions",
                    entity_id=str(execution_id),
                    performed_by_user_id=None,
                    changes_json={"queue_job_id": str(queue_job_id), "worker_name": worker_name},
                    ip_address=None,
                )
            )
            self.operational_session.commit()
            logger.info("Execution processing started.", extra={"execution_id": str(execution_id), "worker_name": worker_name})

            request_file = self.request_files.get_by_id(queue_job.request_file_id)
            if request_file is None:
                raise AppException("Request file not found for execution.", status_code=404, code="request_file_not_found")

            shared_request = self.shared_analysis.get_request_by_id(shared_execution.analysis_request_id)
            if shared_request is None:
                raise AppException("Related analysis request not found.", status_code=404, code="analysis_request_not_found")

            resolved_runtime = self.runtime_resolver.resolve(shared_request.automation_id)
            logger.info(
                "Execution runtime resolved from shared system.",
                extra={
                    "execution_id": str(execution_id),
                    "event": "runtime_config_resolved",
                    "provider": resolved_runtime.provider_slug,
                    "model": resolved_runtime.model_slug,
                    "prompt_version": resolved_runtime.prompt_version,
                },
            )
            runtime = self.provider_service.resolve_runtime(
                provider_slug=resolved_runtime.provider_slug,
                model_slug=resolved_runtime.model_slug,
            )
            logger.info(
                "Operational provider/model validation succeeded.",
                extra={
                    "execution_id": str(execution_id),
                    "event": "runtime_validation_ok",
                    "provider": runtime.provider.slug,
                    "model": runtime.model.model_slug,
                },
            )

            input_file_content = self._read_input_file_content(
                file_path=request_file.file_path,
                file_name=request_file.file_name,
            )
            content_chunks = self._chunk_content(input_file_content)

            self.shared_executions.update_status(execution_id=execution_id, status=ExecutionStatus.GENERATING_OUTPUT.value)
            self.shared_session.commit()

            total_input_tokens = 0
            total_output_tokens = 0
            total_cost = Decimal("0")
            output_chunks: list[str] = []
            providers_used: set[str] = set()
            models_used: set[str] = set()
            started = perf_counter()

            for chunk_index, content_chunk in enumerate(content_chunks, start=1):
                prompt_input = self._build_provider_prompt(
                    official_prompt=resolved_runtime.prompt_text,
                    file_content=content_chunk,
                )

                sanitized_prompt, was_truncated = self._enforce_token_limit(
                    prompt=prompt_input,
                    provider_runtime=runtime,
                )
                if was_truncated:
                    logger.warning(
                        "Prompt content truncated due to token limit.",
                        extra={
                            "execution_id": str(execution_id),
                            "event": "content_truncated",
                            "chunk_index": chunk_index,
                        },
                    )

                provider_result = self._execute_with_runtime(
                    prompt_input=sanitized_prompt,
                    runtime=runtime,
                )

                chunk_cost = runtime.client.estimate_cost(
                    input_tokens=provider_result.input_tokens,
                    output_tokens=provider_result.output_tokens,
                    cost_input_per_1k_tokens=runtime.model.cost_input_per_1k_tokens,
                    cost_output_per_1k_tokens=runtime.model.cost_output_per_1k_tokens,
                )
                if total_cost + chunk_cost > Decimal(str(settings.max_cost_per_execution)):
                    raise AppException(
                        "Execution aborted due to estimated cost limit.",
                        status_code=422,
                        code="cost_limit_exceeded",
                        details={"max_cost_per_execution": settings.max_cost_per_execution},
                    )

                self.usage_service.register_usage(
                    provider_id=runtime.provider.id,
                    model_id=runtime.model.id,
                    execution_id=execution_id,
                    input_tokens=provider_result.input_tokens,
                    output_tokens=provider_result.output_tokens,
                    estimated_cost=chunk_cost,
                )

                total_input_tokens += provider_result.input_tokens
                total_output_tokens += provider_result.output_tokens
                total_cost += chunk_cost
                providers_used.add(runtime.provider.slug)
                models_used.add(runtime.model.model_slug)
                output_chunks.append(provider_result.output_text)

            merged_output = "\n\n".join(output_chunks)
            self.file_service.register_generated_execution_file(
                execution_id=execution_id,
                file_type="output",
                file_name=f"execution_{execution_id}.txt",
                content=merged_output.encode("utf-8"),
                mime_type="text/plain",
            )

            queue_job.job_status = ExecutionStatus.COMPLETED.value
            queue_job.error_message = None
            queue_job.finished_at = datetime.now(timezone.utc)
            self.shared_executions.update_status(execution_id=execution_id, status=ExecutionStatus.COMPLETED.value)
            self.audit_logs.add(
                DjangoAiAuditLog(
                    action_type="execution_completed",
                    entity_type="analysis_executions",
                    entity_id=str(execution_id),
                    performed_by_user_id=None,
                    changes_json={
                        "queue_job_id": str(queue_job_id),
                        "providers_used": sorted(providers_used),
                        "models_used": sorted(models_used),
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "estimated_cost": str(total_cost),
                    },
                    ip_address=None,
                )
            )
            self.operational_session.commit()
            self.shared_session.commit()
            logger.info(
                "Execution processing completed.",
                extra={
                    "execution_id": str(execution_id),
                    "provider": ",".join(sorted(providers_used)) if providers_used else None,
                    "model": ",".join(sorted(models_used)) if models_used else None,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "estimated_cost": str(total_cost),
                    "duration_seconds": round(perf_counter() - started, 4),
                },
            )
        except Exception as exc:
            logger.exception("Execution processing failed.", extra={"execution_id": str(execution_id)}, exc_info=exc)
            if self._should_retry(exc=exc, retry_count=queue_job.retry_count or 0):
                self._schedule_retry(
                    execution_id=execution_id,
                    queue_job=queue_job,
                    reason=self._error_message(exc),
                    worker_name=worker_name,
                    correlation_id=correlation_id,
                )
                return

            self._mark_execution_failed(
                execution_id=execution_id,
                queue_job_id=queue_job_id,
                error_message=self._error_message(exc),
                worker_name=worker_name,
                ip_address=None,
                register_error_file=True,
            )

    def _read_input_file_content(self, *, file_path: str, file_name: str) -> str:
        extension = Path(file_name).suffix.lower()
        with self.file_service.storage.open_file(file_path) as handle:
            if extension == ".csv":
                return handle.read().decode("utf-8", errors="ignore")
            if extension == ".pdf":
                return self._extract_pdf_text(handle.read())
            if extension == ".xlsx":
                return self._extract_xlsx_text(handle.read())
            raw_bytes = handle.read()
            return raw_bytes.decode("utf-8", errors="ignore")

    @staticmethod
    def _extract_pdf_text(content: bytes) -> str:
        try:
            from pypdf import PdfReader
        except Exception:
            return content[:8000].decode("utf-8", errors="ignore")

        try:
            import io

            reader = PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages[:20]:
                pages.append(page.extract_text() or "")
            return "\n".join(pages).strip()
        except Exception:
            return content[:8000].decode("utf-8", errors="ignore")

    @staticmethod
    def _extract_xlsx_text(content: bytes) -> str:
        try:
            from openpyxl import load_workbook
        except Exception:
            return content[:8000].decode("utf-8", errors="ignore")

        try:
            import io

            workbook = load_workbook(filename=io.BytesIO(content), read_only=True, data_only=True)
            rows_text: list[str] = []
            for sheet in workbook.worksheets[:3]:
                for row in sheet.iter_rows(min_row=1, max_row=500, values_only=True):
                    values = [str(value) for value in row if value is not None]
                    if values:
                        rows_text.append(", ".join(values))
            return "\n".join(rows_text).strip()
        except Exception:
            return content[:8000].decode("utf-8", errors="ignore")

    def _chunk_content(self, content: str) -> list[str]:
        normalized = content.strip()
        if not normalized:
            return ["(arquivo sem conteudo textual)"]

        if len(normalized) > settings.max_input_characters:
            logger.warning(
                "Input content exceeded max_input_characters; truncating before chunking.",
                extra={"event": "content_truncated"},
            )
            normalized = normalized[: settings.max_input_characters]

        if len(normalized) <= settings.chunk_size_characters:
            return [normalized]

        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(start + settings.chunk_size_characters, len(normalized))
            chunks.append(normalized[start:end])
            start = end
        return chunks

    @staticmethod
    def _build_provider_prompt(*, official_prompt: str, file_content: str) -> str:
        return f"Analise o seguinte arquivo:\n{file_content}\n\nPrompt oficial da automacao:\n{official_prompt}"

    def _enforce_token_limit(
        self,
        *,
        prompt: str,
        provider_runtime: ProviderRuntimeSelection,
    ) -> tuple[str, bool]:
        max_tokens_allowed = max(settings.max_tokens_per_execution, 1)
        current_prompt = prompt
        current_tokens = provider_runtime.client.count_tokens(current_prompt)
        if current_tokens <= max_tokens_allowed:
            return current_prompt, False

        was_truncated = False
        for _ in range(12):
            ratio = max_tokens_allowed / max(current_tokens, 1)
            new_length = max(500, int(len(current_prompt) * ratio * 0.9))
            if new_length >= len(current_prompt):
                new_length = len(current_prompt) - 1
            if new_length <= 0:
                break
            current_prompt = current_prompt[:new_length]
            current_tokens = provider_runtime.client.count_tokens(current_prompt)
            was_truncated = True
            if current_tokens <= max_tokens_allowed:
                return current_prompt, was_truncated

        raise AppException(
            "Prompt exceeds configured token limit for execution.",
            status_code=422,
            code="prompt_token_limit_exceeded",
            details={"max_tokens_per_execution": settings.max_tokens_per_execution},
        )

    def _execute_with_runtime(
        self,
        *,
        prompt_input: str,
        runtime: ProviderRuntimeSelection,
    ) -> ProviderExecutionResult:
        context_tokens = bind_log_context(
            provider=runtime.provider.slug,
            model=runtime.model.model_slug,
        )
        try:
            return runtime.client.execute_prompt(
                prompt=prompt_input,
                model_name=runtime.model.model_slug,
                max_tokens=settings.max_tokens,
                temperature=settings.temperature,
            )
        finally:
            reset_log_context(context_tokens)

    def _is_concurrency_limited(self, *, queue_job_id: UUID) -> bool:
        processing = self.queue_jobs.count_processing_jobs(exclude_queue_job_id=queue_job_id)
        return processing >= settings.max_concurrent_executions

    def _schedule_retry(
        self,
        *,
        execution_id: UUID,
        queue_job: DjangoAiQueueJob,
        reason: str,
        worker_name: str,
        correlation_id: str | None,
    ) -> None:
        current_retry = queue_job.retry_count or 0
        if current_retry >= settings.max_retries:
            self._mark_execution_failed(
                execution_id=execution_id,
                queue_job_id=queue_job.id,
                error_message=reason,
                worker_name=worker_name,
                ip_address=None,
                register_error_file=True,
            )
            return

        next_retry = current_retry + 1
        backoff_base = settings.retry_backoff or settings.retry_backoff_seconds
        delay_seconds = backoff_base * (2 ** (next_retry - 1))
        delay_ms = delay_seconds * 1000

        self.operational_session.rollback()
        self.shared_session.rollback()
        self.queue_jobs.mark_queued_for_retry(
            queue_job_id=queue_job.id,
            retry_count=next_retry,
            error_message=reason,
        )
        self.shared_executions.update_status(execution_id=execution_id, status=ExecutionStatus.QUEUED.value)
        self.audit_logs.add(
            DjangoAiAuditLog(
                action_type="execution_retry_scheduled",
                entity_type="analysis_executions",
                entity_id=str(execution_id),
                performed_by_user_id=None,
                changes_json={
                    "queue_job_id": str(queue_job.id),
                    "retry_attempt": next_retry,
                    "max_retries": settings.max_retries,
                    "delay_seconds": delay_seconds,
                    "reason": reason[:200],
                },
                ip_address=None,
            )
        )
        self.operational_session.commit()
        self.shared_session.commit()
        logger.warning(
            "Retry scheduled for execution.",
            extra={
                "execution_id": str(execution_id),
                "event": "retry_attempt",
                "status": "queued",
                "queue_job_id": str(queue_job.id),
                "retry_attempt": next_retry,
                "delay_seconds": delay_seconds,
            },
        )
        enqueue_execution_job(
            execution_id=execution_id,
            queue_job_id=queue_job.id,
            correlation_id=correlation_id,
            delay_ms=delay_ms,
        )

    def _should_retry(self, *, exc: Exception, retry_count: int) -> bool:
        if retry_count >= settings.max_retries:
            return False
        if self._is_retryable_provider_exception(exc):
            return True
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return True
        return False

    def _is_retryable_provider_exception(self, exc: Exception) -> bool:
        if not isinstance(exc, AppException):
            return False
        if exc.payload.code in RETRYABLE_ERROR_CODES:
            return True
        if exc.payload.code == "provider_http_error":
            status_code = (exc.payload.details or {}).get("status_code")
            try:
                status_code_int = int(status_code)
            except (TypeError, ValueError):
                return False
            return status_code_int in RETRYABLE_PROVIDER_STATUS_CODES
        return False

    @staticmethod
    def _error_message(exc: Exception) -> str:
        if isinstance(exc, AppException):
            return exc.payload.message
        return str(exc)

    def _mark_execution_failed(
        self,
        *,
        execution_id: UUID,
        queue_job_id: UUID,
        error_message: str,
        worker_name: str,
        ip_address: str | None,
        register_error_file: bool,
    ) -> None:
        self.operational_session.rollback()
        self.shared_session.rollback()

        queue_job = self.queue_jobs.get_by_id(queue_job_id)
        if queue_job is not None:
            queue_job.job_status = ExecutionStatus.FAILED.value
            queue_job.error_message = error_message[:2000]
            queue_job.worker_name = worker_name
            queue_job.finished_at = datetime.now(timezone.utc)
            queue_job.retry_count = max(queue_job.retry_count or 0, 0)

        if register_error_file:
            self._register_error_file(execution_id=execution_id, error_message=error_message)

        self.shared_executions.update_status(execution_id=execution_id, status=ExecutionStatus.FAILED.value)
        self.audit_logs.add(
            DjangoAiAuditLog(
                action_type="execution_failed",
                entity_type="analysis_executions",
                entity_id=str(execution_id),
                performed_by_user_id=None,
                changes_json={
                    "queue_job_id": str(queue_job_id),
                    "error_message": error_message[:500],
                },
                ip_address=ip_address,
            )
        )

        self.operational_session.commit()
        self.shared_session.commit()
        logger.error(
            "Execution marked as failed.",
            extra={
                "execution_id": str(execution_id),
                "event": "execution_failed",
                "queue_job_id": str(queue_job_id),
            },
        )

    def _register_error_file(self, *, execution_id: UUID, error_message: str) -> None:
        try:
            self.file_service.register_generated_execution_file(
                execution_id=execution_id,
                file_type="error",
                file_name=f"execution_{execution_id}_error.txt",
                content=error_message[:5000].encode("utf-8"),
                mime_type="text/plain",
            )
        except Exception:
            logger.exception(
                "Failed to register execution error file.",
                extra={"execution_id": str(execution_id)},
            )

    @staticmethod
    def _parse_status(raw_status: str) -> ExecutionStatus:
        try:
            return ExecutionStatus(raw_status)
        except ValueError:
            return ExecutionStatus.FAILED
