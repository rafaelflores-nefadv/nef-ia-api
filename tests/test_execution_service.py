from datetime import datetime, timezone
import io
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from openpyxl import load_workbook

from app.core.constants import ExecutionStatus
from app.core.exceptions import AppException
from app.integrations.providers.base import ProviderExecutionResult
from app.models.operational import (
    DjangoAiApiToken,
    DjangoAiApiTokenPermission,
    DjangoAiQueueJob,
    DjangoAiRequestFile,
)
from app.models.shared import AnalysisExecution
from app.services import execution_service as execution_module
from app.services.execution_service import ExecutionService


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


class FakeRequestFileRepository:
    def __init__(self, request_files: dict[UUID, DjangoAiRequestFile]) -> None:
        self.request_files = request_files

    def get_by_id(self, file_id: UUID) -> DjangoAiRequestFile | None:
        return self.request_files.get(file_id)


class FakeQueueRepository:
    def __init__(self) -> None:
        self.jobs: dict[UUID, DjangoAiQueueJob] = {}
        self.processing_count = 0

    def add(self, job: DjangoAiQueueJob) -> DjangoAiQueueJob:
        if job.id is None:
            job.id = uuid4()
        self.jobs[job.id] = job
        return job

    def get_by_id(self, job_id: UUID) -> DjangoAiQueueJob | None:
        return self.jobs.get(job_id)

    def get_latest_by_execution_id(self, execution_id: UUID) -> DjangoAiQueueJob | None:
        matches = [job for job in self.jobs.values() if job.execution_id == execution_id]
        return matches[-1] if matches else None

    def acquire_for_processing(self, *, queue_job_id: UUID, worker_name: str, started_at) -> bool:  # type: ignore[no-untyped-def]
        job = self.jobs.get(queue_job_id)
        if job is None:
            return False
        if job.job_status not in {ExecutionStatus.QUEUED.value, ExecutionStatus.PENDING.value}:
            return False
        job.job_status = ExecutionStatus.PROCESSING.value
        job.worker_name = worker_name
        job.started_at = started_at
        job.finished_at = None
        job.error_message = None
        return True

    def mark_queued_for_retry(self, *, queue_job_id: UUID, retry_count: int, error_message: str) -> bool:
        job = self.jobs.get(queue_job_id)
        if job is None:
            return False
        job.job_status = ExecutionStatus.QUEUED.value
        job.retry_count = retry_count
        job.error_message = error_message
        job.started_at = None
        job.finished_at = None
        return True

    def count_processing_jobs(self, *, exclude_queue_job_id: UUID | None = None) -> int:
        return self.processing_count


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list[object] = []

    def add(self, event: object) -> object:
        self.events.append(event)
        return event


class FakeSharedAnalysisRepository:
    def __init__(self, requests: dict[UUID, object]) -> None:
        self.requests = requests

    def get_request_by_id(self, analysis_request_id: UUID):  # type: ignore[no-untyped-def]
        return self.requests.get(analysis_request_id)


class FakeSharedExecutionRepository:
    def __init__(self) -> None:
        self.executions: dict[UUID, AnalysisExecution] = {}

    def create(self, *, analysis_request_id: UUID, status: str) -> AnalysisExecution:
        execution = AnalysisExecution(
            id=uuid4(),
            analysis_request_id=analysis_request_id,
            status=status,
            created_at=datetime.now(timezone.utc),
        )
        self.executions[execution.id] = execution
        return execution

    def get_by_id(self, execution_id: UUID) -> AnalysisExecution | None:
        return self.executions.get(execution_id)

    def list_by_analysis_request_id(self, analysis_request_id: UUID) -> list[AnalysisExecution]:
        return [item for item in self.executions.values() if item.analysis_request_id == analysis_request_id]

    def update_status(self, *, execution_id: UUID, status: str) -> AnalysisExecution | None:
        execution = self.executions.get(execution_id)
        if execution is None:
            return None
        execution.status = status
        return execution


class FakeAutomationRuntimeResolver:
    def __init__(self, *, provider_slug: str = "openai", model_slug: str = "gpt-5", prompt_text: str = "Prompt oficial") -> None:
        self.provider_slug = provider_slug
        self.model_slug = model_slug
        self.prompt_text = prompt_text
        self.resolve_calls: list[UUID] = []

    def resolve(self, automation_id):  # type: ignore[no-untyped-def]
        self.resolve_calls.append(automation_id)
        return SimpleNamespace(
            automation_id=automation_id,
            prompt_text=self.prompt_text,
            prompt_version=3,
            provider_slug=self.provider_slug,
            model_slug=self.model_slug,
        )


class FakeFileService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def register_generated_execution_file(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return SimpleNamespace(id=uuid4())


class FakeProviderClient:
    def __init__(
        self,
        *,
        modes: list[str] | None = None,
        input_tokens: int = 150,
        output_tokens: int = 75,
        estimated_cost: Decimal = Decimal("0.022500"),
        output_text: str = (
            "Classificacao da planilha: Classe A\n"
            "Classificacao correta: Classe B\n"
            "Veredito: Divergente\n"
            "Motivo: Fundamentacao teste\n"
            "Trecho determinante: Trecho teste"
        ),
    ) -> None:
        self.modes = modes or ["success"]
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.estimated_cost = estimated_cost
        self.output_text = output_text
        self.execute_calls: list[dict] = []

    def execute_prompt(self, **kwargs):  # type: ignore[no-untyped-def]
        self.execute_calls.append(kwargs)
        mode = self.modes.pop(0) if self.modes else "success"
        if mode == "timeout":
            raise AppException("Provider request timed out.", status_code=504, code="provider_timeout")
        if mode == "network":
            raise AppException("Network error.", status_code=502, code="provider_network_error")
        if mode == "logic_error":
            raise AppException("Invalid input.", status_code=422, code="invalid_input")
        return ProviderExecutionResult(
            output_text=self.output_text,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            raw_response={"id": "resp_test"},
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def estimate_cost(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.estimated_cost


class FakeProviderService:
    def __init__(self, client: FakeProviderClient, *, resolve_error: AppException | None = None) -> None:
        self.client = client
        self.resolve_error = resolve_error
        self.resolve_calls: list[tuple[str, str]] = []
        self.provider_id = uuid4()
        self.model_id = uuid4()

    def resolve_runtime(self, *, provider_slug: str, model_slug: str):  # type: ignore[no-untyped-def]
        self.resolve_calls.append((provider_slug, model_slug))
        if self.resolve_error is not None:
            raise self.resolve_error
        return SimpleNamespace(
            provider=SimpleNamespace(id=self.provider_id, slug=provider_slug),
            model=SimpleNamespace(
                id=self.model_id,
                model_slug=model_slug,
                cost_input_per_1k_tokens=Decimal("0.150000"),
                cost_output_per_1k_tokens=Decimal("0.600000"),
            ),
            credential=SimpleNamespace(id=uuid4()),
            client=self.client,
        )


class FakeUsageService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def register_usage(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return SimpleNamespace(id=uuid4())


def _build_permission(automation_id: UUID) -> DjangoAiApiTokenPermission:
    return DjangoAiApiTokenPermission(
        token_id=uuid4(),
        automation_id=automation_id,
        provider_id=None,
        allow_execution=True,
        allow_file_upload=False,
    )


def _build_api_token() -> DjangoAiApiToken:
    return DjangoAiApiToken(
        id=uuid4(),
        name="exec-token",
        token_hash="hash",
        is_active=True,
        expires_at=None,
        created_by_user_id=uuid4(),
    )


def _build_request_file(analysis_request_id: UUID, *, file_name: str = "input.pdf") -> DjangoAiRequestFile:
    return DjangoAiRequestFile(
        id=uuid4(),
        analysis_request_id=analysis_request_id,
        file_name=file_name,
        file_path="requests/test/input.csv",
        file_size=25,
        mime_type="text/csv",
        checksum="checksum",
        uploaded_at=datetime.now(timezone.utc),
    )


def _seed_execution_and_job(
    *,
    shared_exec_repo: FakeSharedExecutionRepository,
    queue_repo: FakeQueueRepository,
    analysis_request_id: UUID,
    request_file_id: UUID,
    status: ExecutionStatus = ExecutionStatus.QUEUED,
    retry_count: int = 0,
) -> tuple[AnalysisExecution, DjangoAiQueueJob]:
    execution = shared_exec_repo.create(analysis_request_id=analysis_request_id, status=status.value)
    queue_job = DjangoAiQueueJob(
        id=uuid4(),
        execution_id=execution.id,
        request_file_id=request_file_id,
        job_status=ExecutionStatus.QUEUED.value,
        retry_count=retry_count,
    )
    queue_repo.add(queue_job)
    return execution, queue_job


def _build_service(
    analysis_request_id: UUID,
    automation_id: UUID,
    request_file: DjangoAiRequestFile,
) -> tuple[ExecutionService, FakeQueueRepository, FakeSharedExecutionRepository]:
    operational_session = FakeSession()
    shared_session = FakeSession()
    service = ExecutionService(operational_session=operational_session, shared_session=shared_session)  # type: ignore[arg-type]
    queue_repo = FakeQueueRepository()
    shared_exec_repo = FakeSharedExecutionRepository()
    service.request_files = FakeRequestFileRepository({request_file.id: request_file})  # type: ignore[assignment]
    service.queue_jobs = queue_repo  # type: ignore[assignment]
    service.audit_logs = FakeAuditRepository()  # type: ignore[assignment]
    service.shared_analysis = FakeSharedAnalysisRepository(
        {analysis_request_id: SimpleNamespace(id=analysis_request_id, automation_id=automation_id)}
    )  # type: ignore[assignment]
    service.shared_executions = shared_exec_repo  # type: ignore[assignment]
    service.runtime_resolver = FakeAutomationRuntimeResolver()  # type: ignore[assignment]
    service.file_service = FakeFileService()  # type: ignore[assignment]
    service.usage_service = FakeUsageService()  # type: ignore[assignment]
    return service, queue_repo, shared_exec_repo


def test_create_execution_creates_queue_job_and_dispatches(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    permissions = [_build_permission(automation_id)]
    dispatched: list[tuple[UUID, UUID, int | None]] = []

    monkeypatch.setattr(
        "app.services.execution_service.enqueue_execution_job",
        lambda *, execution_id, queue_job_id, correlation_id=None, delay_ms=None: dispatched.append((execution_id, queue_job_id, delay_ms)),
    )

    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    result = service.create_execution(
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
        api_token=_build_api_token(),
        token_permissions=permissions,
    )

    assert result.status == ExecutionStatus.QUEUED
    assert result.execution_id in shared_exec_repo.executions
    assert result.queue_job_id in queue_repo.jobs
    assert len(dispatched) == 1
    assert dispatched[0][2] is None


def test_execution_uses_exact_provider_and_model_from_shared(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    service.runtime_resolver = FakeAutomationRuntimeResolver(provider_slug="openai", model_slug="gpt-5")  # type: ignore[assignment]
    provider_service = FakeProviderService(FakeProviderClient(modes=["success"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "conteudo arquivo")
    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.COMPLETED.value
    assert provider_service.resolve_calls == [("openai", "gpt-5")]
    assert provider_service.client.execute_calls
    assert provider_service.client.execute_calls[0]["model_name"] == "gpt-5"


def test_fails_when_provider_is_inactive(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    service.runtime_resolver = FakeAutomationRuntimeResolver(provider_slug="openai", model_slug="gpt-5")  # type: ignore[assignment]
    service.provider_service = FakeProviderService(  # type: ignore[assignment]
        FakeProviderClient(),
        resolve_error=AppException("Provider inactive.", status_code=422, code="provider_inactive"),
    )

    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "conteudo arquivo")
    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.FAILED.value
    assert "inactive" in (queue_repo.jobs[queue_job.id].error_message or "").lower()


def test_fails_when_model_is_inactive(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    service.runtime_resolver = FakeAutomationRuntimeResolver(provider_slug="openai", model_slug="gpt-5")  # type: ignore[assignment]
    service.provider_service = FakeProviderService(  # type: ignore[assignment]
        FakeProviderClient(),
        resolve_error=AppException("Model inactive.", status_code=422, code="provider_model_inactive"),
    )

    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "conteudo arquivo")
    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert "model inactive" in (queue_repo.jobs[queue_job.id].error_message or "").lower()


def test_fails_when_model_does_not_belong_to_provider(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    service.runtime_resolver = FakeAutomationRuntimeResolver(provider_slug="openai", model_slug="claude-sonnet")  # type: ignore[assignment]
    service.provider_service = FakeProviderService(  # type: ignore[assignment]
        FakeProviderClient(),
        resolve_error=AppException("Model mismatch.", status_code=422, code="provider_model_mismatch"),
    )

    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "conteudo arquivo")
    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert "mismatch" in (queue_repo.jobs[queue_job.id].error_message or "").lower()


def test_fails_when_no_active_credential(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    service.runtime_resolver = FakeAutomationRuntimeResolver(provider_slug="openai", model_slug="gpt-5")  # type: ignore[assignment]
    service.provider_service = FakeProviderService(  # type: ignore[assignment]
        FakeProviderClient(),
        resolve_error=AppException("No active credential found.", status_code=422, code="provider_credential_not_found"),
    )

    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "conteudo arquivo")
    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert "credential" in (queue_repo.jobs[queue_job.id].error_message or "").lower()


def test_no_automatic_fallback_when_provider_times_out(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    service.runtime_resolver = FakeAutomationRuntimeResolver(provider_slug="openai", model_slug="gpt-5")  # type: ignore[assignment]
    provider_service = FakeProviderService(FakeProviderClient(modes=["timeout"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "conteudo arquivo")
    monkeypatch.setattr(execution_module.settings, "max_retries", 3)
    monkeypatch.setattr(execution_module.settings, "retry_backoff_seconds", 2)
    dispatched: list[int | None] = []
    monkeypatch.setattr(
        "app.services.execution_service.enqueue_execution_job",
        lambda *, execution_id, queue_job_id, correlation_id=None, delay_ms=None: dispatched.append(delay_ms),
    )

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.QUEUED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.QUEUED.value
    assert queue_repo.jobs[queue_job.id].retry_count == 1
    assert provider_service.resolve_calls == [("openai", "gpt-5")]
    assert len(provider_service.client.execute_calls) == 1
    assert dispatched and dispatched[0] == 2000


def test_retry_keeps_same_provider_and_model(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    service.runtime_resolver = FakeAutomationRuntimeResolver(provider_slug="openai", model_slug="gpt-5")  # type: ignore[assignment]
    provider_service = FakeProviderService(FakeProviderClient(modes=["timeout", "success"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "conteudo arquivo")
    monkeypatch.setattr(execution_module.settings, "max_retries", 3)
    monkeypatch.setattr(execution_module.settings, "retry_backoff_seconds", 1)
    monkeypatch.setattr(
        "app.services.execution_service.enqueue_execution_job",
        lambda *, execution_id, queue_job_id, correlation_id=None, delay_ms=None: None,
    )

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.COMPLETED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.COMPLETED.value
    assert provider_service.resolve_calls == [("openai", "gpt-5"), ("openai", "gpt-5")]
    assert len(provider_service.client.execute_calls) == 2


def test_idempotency_skips_when_execution_already_completed(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(FakeProviderClient(modes=["success"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    execution = shared_exec_repo.create(analysis_request_id=analysis_request_id, status=ExecutionStatus.COMPLETED.value)
    queue_job = DjangoAiQueueJob(
        id=uuid4(),
        execution_id=execution.id,
        request_file_id=request_file.id,
        job_status=ExecutionStatus.QUEUED.value,
        retry_count=0,
    )
    queue_repo.add(queue_job)

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert len(provider_service.client.execute_calls) == 0
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.QUEUED.value


def test_cost_limit_aborts_execution(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    expensive_provider = FakeProviderService(
        FakeProviderClient(modes=["success"], estimated_cost=Decimal("999.000000"))
    )
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    service.provider_service = expensive_provider  # type: ignore[assignment]

    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "conteudo arquivo")
    monkeypatch.setattr(execution_module.settings, "max_cost_per_execution", 0.10)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.FAILED.value
    assert "estimated cost limit" in (queue_repo.jobs[queue_job.id].error_message or "").lower()


def test_token_limit_truncates_prompt(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    provider = FakeProviderService(FakeProviderClient(modes=["success"]))
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    service.provider_service = provider  # type: ignore[assignment]

    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "A" * 4000)
    monkeypatch.setattr(execution_module.settings, "max_tokens_per_execution", 600)
    monkeypatch.setattr(execution_module.settings, "chunk_size_characters", 4000)
    monkeypatch.setattr(execution_module.settings, "max_input_characters", 4000)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert provider.client.execute_calls
    prompt_sent = provider.client.execute_calls[0]["prompt"]
    assert provider.client.count_tokens(prompt_sent) <= 600


def test_concurrency_limit_schedules_retry(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    service.provider_service = FakeProviderService(FakeProviderClient(modes=["success"]))  # type: ignore[assignment]
    queue_repo.processing_count = 10

    monkeypatch.setattr(execution_module.settings, "max_concurrent_executions", 2)
    monkeypatch.setattr(execution_module.settings, "max_retries", 3)
    monkeypatch.setattr(execution_module.settings, "retry_backoff", 1)
    monkeypatch.setattr(execution_module.settings, "retry_backoff_seconds", 1)
    dispatched: list[int | None] = []
    monkeypatch.setattr(
        "app.services.execution_service.enqueue_execution_job",
        lambda *, execution_id, queue_job_id, correlation_id=None, delay_ms=None: dispatched.append(delay_ms),
    )

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.QUEUED.value
    assert queue_repo.jobs[queue_job.id].retry_count == 1
    assert dispatched and dispatched[0] == 1000


def test_tabular_csv_processes_each_row_and_generates_xlsx(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="input.csv")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(FakeProviderClient(modes=["success", "success", "success"]))
    service.provider_service = provider_service  # type: ignore[assignment]
    service.runtime_resolver = FakeAutomationRuntimeResolver(  # type: ignore[assignment]
        prompt_text=(
            "Conteudo: {{CONTEUDO}}\n"
            "Prazo: {{PRAZO_AGENDADO}}\n"
            "Valor: {{VALOR_DA_CAUSA}}\n"
            "Acao: {{TIPO_DE_ACAO}}"
        )
    )

    csv_payload = (
        "processo,conteudo,prazo agendado,valor da causa,tipo de acao\n"
        "P1,Conteudo linha 1,2026-01-10,1000,Acao A\n"
        "P2,Conteudo linha 2,2026-01-11,2000,Acao B\n"
        "P3,Conteudo linha 3,2026-01-12,3000,Acao C\n"
    ).encode("utf-8")
    monkeypatch.setattr(service, "_read_input_file_bytes", lambda **_: csv_payload)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.COMPLETED.value
    assert len(provider_service.client.execute_calls) == 3
    assert "Conteudo linha 1" in provider_service.client.execute_calls[0]["prompt"]

    assert service.file_service.calls
    generated = service.file_service.calls[0]
    assert generated["file_type"] == "output"
    assert generated["file_name"].endswith("_resultado.xlsx")
    assert generated["mime_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    workbook = load_workbook(io.BytesIO(generated["content"]))
    sheet = workbook.active
    header = [str(item or "") for item in next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))]
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    assert len(rows) == 3
    assert "classificacao_correta" in header
    assert "veredito" in header


def test_tabular_csv_row_error_does_not_abort_execution(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="input.csv")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(
        FakeProviderClient(modes=["success", "logic_error", "success"])
    )
    service.provider_service = provider_service  # type: ignore[assignment]
    service.runtime_resolver = FakeAutomationRuntimeResolver(  # type: ignore[assignment]
        prompt_text="Conteudo: {{CONTEUDO}}"
    )

    csv_payload = (
        "conteudo,prazo agendado\n"
        "Conteudo linha 1,2026-01-10\n"
        "Conteudo linha 2,2026-01-11\n"
        "Conteudo linha 3,2026-01-12\n"
    ).encode("utf-8")
    monkeypatch.setattr(service, "_read_input_file_bytes", lambda **_: csv_payload)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.COMPLETED.value
    assert len(provider_service.client.execute_calls) == 3
    assert len(service.usage_service.calls) == 2

    generated = service.file_service.calls[0]
    workbook = load_workbook(io.BytesIO(generated["content"]))
    sheet = workbook.active
    header = [str(item or "") for item in next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))]
    status_index = header.index("status")
    error_index = header.index("erro")
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    statuses = [str(row[status_index] or "") for row in rows]
    errors = [str(row[error_index] or "") for row in rows]
    assert statuses == ["ok", "erro", "ok"]
    assert "Invalid input." in errors[1]
