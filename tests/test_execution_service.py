from datetime import datetime, timezone
import io
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from openpyxl import Workbook, load_workbook

from app.core.constants import ExecutionStatus
from app.core.exceptions import AppException
from app.integrations.providers.base import ProviderExecutionResult
from app.models.operational import (
    DjangoAiApiToken,
    DjangoAiApiTokenPermission,
    DjangoAiAutomationExecutionSetting,
    DjangoAiExecutionInputFile,
    DjangoAiQueueJob,
    DjangoAiRequestFile,
)
from app.models.shared import AnalysisExecution
from app.services import execution_service as execution_module
from app.services.execution_engine import EngineExecutionInput, ExecutionFileKind
from app.services.execution_service import ExecutionService, PromptTestExecutionContextInput


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

    def list_by_execution_id(self, execution_id: UUID) -> list[DjangoAiQueueJob]:
        return [job for job in self.jobs.values() if job.execution_id == execution_id]

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


class FakeExecutionInputRepository:
    def __init__(self) -> None:
        self.items: list[object] = []

    def add(self, model):  # type: ignore[no-untyped-def]
        self.items.append(model)
        return model

    def list_by_execution_id(self, execution_id: UUID) -> list[object]:
        return [item for item in self.items if getattr(item, "execution_id", None) == execution_id]

    def get_primary_by_execution_id(self, execution_id: UUID):  # type: ignore[no-untyped-def]
        matches = [
            item
            for item in self.items
            if getattr(item, "execution_id", None) == execution_id and getattr(item, "role", "") == "primary"
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: (int(getattr(item, "order_index", 0)), str(getattr(item, "created_at", ""))))
        return matches[0]


class FakeAutomationExecutionSettingsRepository:
    def __init__(self) -> None:
        self.active_settings: dict[UUID, object] = {}

    def get_active_by_automation_id(self, automation_id: UUID):  # type: ignore[no-untyped-def]
        return self.active_settings.get(automation_id)


class FakePromptTestExecutionContextRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, object] = {}

    def add(self, model):  # type: ignore[no-untyped-def]
        self.items[model.execution_id] = model
        return model

    def get_by_execution_id(self, execution_id: UUID):  # type: ignore[no-untyped-def]
        return self.items.get(execution_id)


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
        self.resolve_require_prompt_calls: list[bool] = []

    def resolve(self, automation_id, *, require_prompt: bool = True):  # type: ignore[no-untyped-def]
        self.resolve_calls.append(automation_id)
        self.resolve_require_prompt_calls.append(require_prompt)
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


def _build_request_file(
    analysis_request_id: UUID,
    *,
    file_name: str = "input.pdf",
    file_path: str | None = None,
    mime_type: str = "text/csv",
) -> DjangoAiRequestFile:
    return DjangoAiRequestFile(
        id=uuid4(),
        analysis_request_id=analysis_request_id,
        file_name=file_name,
        file_path=file_path or f"requests/test/{uuid4()}_{file_name}",
        file_size=25,
        mime_type=mime_type,
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
    service.execution_inputs = FakeExecutionInputRepository()  # type: ignore[assignment]
    service.execution_profile_settings = FakeAutomationExecutionSettingsRepository()  # type: ignore[assignment]
    service.prompt_test_execution_contexts = FakePromptTestExecutionContextRepository()  # type: ignore[assignment]
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


def test_create_execution_persists_prompt_test_context(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    permissions = [_build_permission(automation_id)]

    monkeypatch.setattr(
        "app.services.execution_service.enqueue_execution_job",
        lambda **kwargs: None,
    )

    service, _, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    result = service.create_execution(
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
        prompt_test_context=PromptTestExecutionContextInput(
            test_automation_id=uuid4(),
            test_automation_name="Teste OCR",
            provider_slug="openai",
            model_slug="gpt-4.1-mini",
        ),
        api_token=_build_api_token(),
        token_permissions=permissions,
    )

    stored_context = service.prompt_test_execution_contexts.get_by_execution_id(result.execution_id)  # type: ignore[attr-defined]
    assert stored_context is not None
    assert stored_context.execution_id == result.execution_id
    assert result.execution_id in shared_exec_repo.executions


def test_create_execution_supports_request_file_ids_and_keeps_primary(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    primary_file = _build_request_file(analysis_request_id, file_name="primary.csv")
    context_file = _build_request_file(analysis_request_id, file_name="context.csv")
    permissions = [_build_permission(automation_id)]
    dispatched: list[tuple[UUID, UUID, int | None]] = []

    monkeypatch.setattr(
        "app.services.execution_service.enqueue_execution_job",
        lambda *, execution_id, queue_job_id, correlation_id=None, delay_ms=None: dispatched.append((execution_id, queue_job_id, delay_ms)),
    )

    service, queue_repo, _ = _build_service(analysis_request_id, automation_id, primary_file)
    service.request_files = FakeRequestFileRepository(  # type: ignore[assignment]
        {
            primary_file.id: primary_file,
            context_file.id: context_file,
        }
    )

    result = service.create_execution(
        analysis_request_id=analysis_request_id,
        request_file_id=None,
        request_file_ids=[primary_file.id, context_file.id],
        api_token=_build_api_token(),
        token_permissions=permissions,
    )

    queue_job = queue_repo.jobs[result.queue_job_id]
    assert queue_job.request_file_id == primary_file.id
    assert len(service.execution_inputs.items) == 2  # type: ignore[attr-defined]
    assert dispatched


def test_create_execution_supports_input_files_roles(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    first_file = _build_request_file(analysis_request_id, file_name="f1.csv")
    second_file = _build_request_file(analysis_request_id, file_name="f2.csv")
    permissions = [_build_permission(automation_id)]

    monkeypatch.setattr(
        "app.services.execution_service.enqueue_execution_job",
        lambda *, execution_id, queue_job_id, correlation_id=None, delay_ms=None: None,
    )

    service, queue_repo, _ = _build_service(analysis_request_id, automation_id, first_file)
    service.request_files = FakeRequestFileRepository(  # type: ignore[assignment]
        {
            first_file.id: first_file,
            second_file.id: second_file,
        }
    )

    result = service.create_execution(
        analysis_request_id=analysis_request_id,
        request_file_id=None,
        input_files=[
            {"request_file_id": second_file.id, "role": "context", "order_index": 1},
            {"request_file_id": first_file.id, "role": "primary", "order_index": 0},
        ],
        api_token=_build_api_token(),
        token_permissions=permissions,
    )

    queue_job = queue_repo.jobs[result.queue_job_id]
    assert queue_job.request_file_id == first_file.id
    roles = {item.request_file_id: item.role for item in service.execution_inputs.items}  # type: ignore[attr-defined]
    assert roles[first_file.id] == "primary"
    assert roles[second_file.id] == "context"


def test_execution_with_prompt_override_skips_official_prompt_requirement(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id)
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    runtime_resolver = FakeAutomationRuntimeResolver(prompt_text="")
    provider_service = FakeProviderService(FakeProviderClient(modes=["success"]))
    service.runtime_resolver = runtime_resolver  # type: ignore[assignment]
    service.provider_service = provider_service  # type: ignore[assignment]

    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "conteudo arquivo")
    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    queue_job.prompt_override_text = "Prompt override para execucao"

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.COMPLETED.value
    assert runtime_resolver.resolve_calls == [automation_id]
    assert runtime_resolver.resolve_require_prompt_calls == [False]
    assert provider_service.client.execute_calls
    sent_prompt = provider_service.client.execute_calls[0]["prompt"]
    assert "Prompt override para execucao" in sent_prompt


def test_list_execution_inputs_returns_legacy_queue_fallback() -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="legacy.csv")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    queue_job.job_status = ExecutionStatus.COMPLETED.value

    inputs = service.list_execution_inputs(
        execution_id=execution.id,
        token_permissions=[_build_permission(automation_id)],
    )
    assert len(inputs) == 1
    assert inputs[0].request_file_id == request_file.id
    assert inputs[0].role == "primary"
    assert inputs[0].source == "legacy_queue_job"


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


def test_tabular_rejects_legacy_xls_extension(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="input.xls")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    service.provider_service = FakeProviderService(FakeProviderClient(modes=["success"]))  # type: ignore[assignment]
    monkeypatch.setattr(service, "_read_input_file_bytes", lambda **_: b"legacy")

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].error_message == "Legacy .xls files are not supported. Convert the spreadsheet to .xlsx."


def test_tabular_json_output_is_parsed(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="input.csv")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(
        FakeProviderClient(
            modes=["success"],
            output_text=(
                '{"classificacao_da_planilha":"A","classificacao_correta":"B",'
                '"veredito":"Divergente","motivo":"Regra","trecho_determinante":"Trecho X"}'
            ),
        )
    )
    service.provider_service = provider_service  # type: ignore[assignment]
    service.runtime_resolver = FakeAutomationRuntimeResolver(  # type: ignore[assignment]
        prompt_text="Conteudo: {{CONTEUDO}}"
    )

    csv_payload = "conteudo\nLinha unica\n".encode("utf-8")
    monkeypatch.setattr(service, "_read_input_file_bytes", lambda **_: csv_payload)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    generated = service.file_service.calls[0]
    workbook = load_workbook(io.BytesIO(generated["content"]))
    sheet = workbook.active
    header = [str(item or "") for item in next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))]
    row = list(sheet.iter_rows(min_row=2, max_row=2, values_only=True))[0]
    verdict_index = header.index("veredito")
    motivo_index = header.index("motivo")
    assert row[verdict_index] == "Divergente"
    assert row[motivo_index] == "Regra"


def test_tabular_chooses_sheet_with_meaningful_header(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="input.xlsx")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(FakeProviderClient(modes=["success"]))
    service.provider_service = provider_service  # type: ignore[assignment]
    service.runtime_resolver = FakeAutomationRuntimeResolver(  # type: ignore[assignment]
        prompt_text="Conteudo: {{CONTEUDO}}"
    )

    workbook = Workbook()
    first = workbook.active
    first.title = "vazia"
    first.append([None, None])
    second = workbook.create_sheet("dados")
    second.append(["conteudo"])
    second.append(["linha da aba correta"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    monkeypatch.setattr(service, "_read_input_file_bytes", lambda **_: buffer.getvalue())

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert len(provider_service.client.execute_calls) == 1
    assert "linha da aba correta" in provider_service.client.execute_calls[0]["prompt"]


def test_tabular_cost_limit_aborts_execution(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="input.csv")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(
        FakeProviderClient(modes=["success"], estimated_cost=Decimal("999.000000"))
    )
    service.provider_service = provider_service  # type: ignore[assignment]
    service.runtime_resolver = FakeAutomationRuntimeResolver(  # type: ignore[assignment]
        prompt_text="Conteudo: {{CONTEUDO}}"
    )

    csv_payload = "conteudo\nlinha 1\nlinha 2\n".encode("utf-8")
    monkeypatch.setattr(service, "_read_input_file_bytes", lambda **_: csv_payload)
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


def test_tabular_primary_with_text_context_applies_context_to_each_row(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    primary_file = _build_request_file(
        analysis_request_id,
        file_name="input.csv",
        file_path="requests/test/primary.csv",
    )
    context_file = _build_request_file(
        analysis_request_id,
        file_name="contexto.pdf",
        file_path="requests/test/contexto.pdf",
        mime_type="application/pdf",
    )
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, primary_file)
    service.request_files = FakeRequestFileRepository(  # type: ignore[assignment]
        {
            primary_file.id: primary_file,
            context_file.id: context_file,
        }
    )

    provider_service = FakeProviderService(FakeProviderClient(modes=["success", "success"]))
    service.provider_service = provider_service  # type: ignore[assignment]
    service.runtime_resolver = FakeAutomationRuntimeResolver(  # type: ignore[assignment]
        prompt_text="Conteudo: {{CONTEUDO}}"
    )

    csv_payload = (
        "conteudo,prazo agendado\n"
        "Linha 1,2026-01-10\n"
        "Linha 2,2026-01-11\n"
    ).encode("utf-8")
    monkeypatch.setattr(service, "_read_input_file_bytes", lambda **_: csv_payload)
    monkeypatch.setattr(
        service,
        "_read_input_file_content",
        lambda **kwargs: "Contexto global de apoio para todas as linhas."
        if kwargs.get("file_path") == context_file.file_path
        else "",
    )

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=primary_file.id,
    )
    service.execution_inputs.add(  # type: ignore[attr-defined]
        DjangoAiExecutionInputFile(
            execution_id=execution.id,
            request_file_id=primary_file.id,
            role="primary",
            order_index=0,
        )
    )
    service.execution_inputs.add(  # type: ignore[attr-defined]
        DjangoAiExecutionInputFile(
            execution_id=execution.id,
            request_file_id=context_file.id,
            role="context",
            order_index=1,
        )
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.COMPLETED.value
    assert len(provider_service.client.execute_calls) == 2
    assert all(
        "Contexto global complementar" in call["prompt"]
        and "Contexto global de apoio" in call["prompt"]
        and "[INSTRUCAO]" in call["prompt"]
        and "[DADOS DA LINHA]" in call["prompt"]
        and "[CONTEXTO]" in call["prompt"]
        for call in provider_service.client.execute_calls
    )


def test_multiple_text_inputs_are_combined_for_single_analysis(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    primary_file = _build_request_file(
        analysis_request_id,
        file_name="principal.pdf",
        file_path="requests/test/principal.pdf",
        mime_type="application/pdf",
    )
    context_file = _build_request_file(
        analysis_request_id,
        file_name="apoio.pdf",
        file_path="requests/test/apoio.pdf",
        mime_type="application/pdf",
    )
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, primary_file)
    service.request_files = FakeRequestFileRepository(  # type: ignore[assignment]
        {
            primary_file.id: primary_file,
            context_file.id: context_file,
        }
    )

    provider_service = FakeProviderService(FakeProviderClient(modes=["success"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    def _read_content(**kwargs):  # type: ignore[no-untyped-def]
        file_path = kwargs.get("file_path")
        if file_path == primary_file.file_path:
            return "Conteudo principal do documento."
        if file_path == context_file.file_path:
            return "Informacoes complementares."
        return ""

    monkeypatch.setattr(service, "_read_input_file_content", _read_content)
    monkeypatch.setattr(execution_module.settings, "chunk_size_characters", 8000)
    monkeypatch.setattr(execution_module.settings, "max_input_characters", 20000)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=primary_file.id,
    )
    service.execution_inputs.add(  # type: ignore[attr-defined]
        DjangoAiExecutionInputFile(
            execution_id=execution.id,
            request_file_id=primary_file.id,
            role="primary",
            order_index=0,
        )
    )
    service.execution_inputs.add(  # type: ignore[attr-defined]
        DjangoAiExecutionInputFile(
            execution_id=execution.id,
            request_file_id=context_file.id,
            role="context",
            order_index=1,
        )
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.COMPLETED.value
    assert len(provider_service.client.execute_calls) == 1
    prompt_sent = provider_service.client.execute_calls[0]["prompt"]
    assert "Documento 1 - principal.pdf" in prompt_sent
    assert "Documento 2 - apoio.pdf" in prompt_sent
    assert "Conteudo principal do documento." in prompt_sent
    assert "Informacoes complementares." in prompt_sent

    generated = service.file_service.calls[0]
    assert generated["file_name"].endswith(".txt")
    assert generated["mime_type"] == "text/plain"


def test_multiple_tabular_inputs_are_rejected_with_clear_error() -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    primary_file = _build_request_file(
        analysis_request_id,
        file_name="primary.csv",
        file_path="requests/test/primary.csv",
    )
    extra_tabular = _build_request_file(
        analysis_request_id,
        file_name="context.xlsx",
        file_path="requests/test/context.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, primary_file)
    service.request_files = FakeRequestFileRepository(  # type: ignore[assignment]
        {
            primary_file.id: primary_file,
            extra_tabular.id: extra_tabular,
        }
    )
    provider_service = FakeProviderService(FakeProviderClient(modes=["success"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=primary_file.id,
    )
    service.execution_inputs.add(  # type: ignore[attr-defined]
        DjangoAiExecutionInputFile(
            execution_id=execution.id,
            request_file_id=primary_file.id,
            role="primary",
            order_index=0,
        )
    )
    service.execution_inputs.add(  # type: ignore[attr-defined]
        DjangoAiExecutionInputFile(
            execution_id=execution.id,
            request_file_id=extra_tabular.id,
            role="context",
            order_index=1,
        )
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.FAILED.value
    assert "multiple tabular files" in (queue_repo.jobs[queue_job.id].error_message or "").lower()
    assert len(provider_service.client.execute_calls) == 0


def test_processing_rejects_inconsistent_roles_without_primary() -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    first_file = _build_request_file(
        analysis_request_id,
        file_name="a.pdf",
        file_path="requests/test/a.pdf",
        mime_type="application/pdf",
    )
    second_file = _build_request_file(
        analysis_request_id,
        file_name="b.pdf",
        file_path="requests/test/b.pdf",
        mime_type="application/pdf",
    )
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, first_file)
    service.request_files = FakeRequestFileRepository(  # type: ignore[assignment]
        {
            first_file.id: first_file,
            second_file.id: second_file,
        }
    )
    provider_service = FakeProviderService(FakeProviderClient(modes=["success"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=first_file.id,
    )
    service.execution_inputs.add(  # type: ignore[attr-defined]
        DjangoAiExecutionInputFile(
            execution_id=execution.id,
            request_file_id=first_file.id,
            role="context",
            order_index=0,
        )
    )
    service.execution_inputs.add(  # type: ignore[attr-defined]
        DjangoAiExecutionInputFile(
            execution_id=execution.id,
            request_file_id=second_file.id,
            role="context",
            order_index=1,
        )
    )

    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.FAILED.value
    assert "exactly one primary file is required" in (queue_repo.jobs[queue_job.id].error_message or "").lower()
    assert len(provider_service.client.execute_calls) == 0


def test_text_prompt_builder_uses_structured_sections() -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="entrada.txt", mime_type="text/plain")
    service, _, _ = _build_service(analysis_request_id, automation_id, request_file)
    execution_profile = service._resolve_execution_profile(automation_id=automation_id)

    prompt = service._build_provider_prompt(
        official_prompt="Resuma o documento de forma objetiva.",
        file_content="Linha 1\n\nLinha 1\nLinha 2",
        execution_profile=execution_profile,
    )

    assert prompt.startswith("[INSTRUCAO]")
    assert "[CONTEXTO]" in prompt
    assert "Arquivo de entrada para analise" in prompt
    assert "Linha 1" in prompt


def test_global_context_prioritizes_type_and_deduplicates_content(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="entrada.csv", mime_type="text/csv")
    service, _, _ = _build_service(analysis_request_id, automation_id, request_file)
    execution_profile = service._resolve_execution_profile(automation_id=automation_id)

    context_inputs = [
        EngineExecutionInput(
            request_file_id=uuid4(),
            role="context",
            order_index=1,
            file_name="ctx_raw.txt",
            file_path="ctx/raw.txt",
            mime_type="text/plain",
            file_kind=ExecutionFileKind.TEXTUAL,
            source="test",
        ),
        EngineExecutionInput(
            request_file_id=uuid4(),
            role="context",
            order_index=1,
            file_name="ctx_structured.json",
            file_path="ctx/structured.json",
            mime_type="application/json",
            file_kind=ExecutionFileKind.TEXTUAL,
            source="test",
        ),
        EngineExecutionInput(
            request_file_id=uuid4(),
            role="context",
            order_index=2,
            file_name="ctx_duplicate.log",
            file_path="ctx/duplicate.log",
            mime_type="text/plain",
            file_kind=ExecutionFileKind.TEXTUAL,
            source="test",
        ),
    ]

    content_map = {
        "ctx/raw.txt": "linha util\n\nlinha util\nlinha final",
        "ctx/structured.json": '{"campo":"valor"}\n{"campo":"valor"}',
        "ctx/duplicate.log": "linha util\nlinha final",
    }
    monkeypatch.setattr(
        service,
        "_read_input_file_content",
        lambda **kwargs: content_map[str(kwargs.get("file_path") or "")],
    )
    monkeypatch.setattr(execution_module.settings, "max_context_file_characters", 5000)
    monkeypatch.setattr(execution_module.settings, "max_context_characters", 5000)

    context_text = service._build_global_context_text(
        context_inputs=context_inputs,
        execution_profile=execution_profile,
    )
    assert context_text is not None
    assert context_text.find("ctx_structured.json") < context_text.find("ctx_raw.txt")
    assert context_text.count("[Contexto ") == 2
    assert "linha util\nlinha util" not in context_text


def test_global_context_applies_per_file_and_total_limits(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="entrada.csv", mime_type="text/csv")
    service, _, _ = _build_service(analysis_request_id, automation_id, request_file)
    execution_profile = service._resolve_execution_profile(automation_id=automation_id)

    context_inputs = [
        EngineExecutionInput(
            request_file_id=uuid4(),
            role="context",
            order_index=0,
            file_name="ctx_a.txt",
            file_path="ctx/a.txt",
            mime_type="text/plain",
            file_kind=ExecutionFileKind.TEXTUAL,
            source="test",
        ),
        EngineExecutionInput(
            request_file_id=uuid4(),
            role="context",
            order_index=1,
            file_name="ctx_b.txt",
            file_path="ctx/b.txt",
            mime_type="text/plain",
            file_kind=ExecutionFileKind.TEXTUAL,
            source="test",
        ),
    ]

    long_text_a = "palavra " * 120
    long_text_b = "diferente " * 120
    monkeypatch.setattr(
        service,
        "_read_input_file_content",
        lambda **kwargs: (
            long_text_a
            if str(kwargs.get("file_path")) == "ctx/a.txt"
            else long_text_b
            if str(kwargs.get("file_path")) == "ctx/b.txt"
            else ""
        ),
    )
    monkeypatch.setattr(execution_module.settings, "max_context_file_characters", 140)
    monkeypatch.setattr(execution_module.settings, "max_context_characters", 260)

    context_text = service._build_global_context_text(
        context_inputs=context_inputs,
        execution_profile=execution_profile,
    )
    assert context_text is not None
    assert len(context_text) <= 260
    assert "contexto truncado para 140 caracteres" in context_text
    assert "contexto truncado para 260 caracteres" in context_text


def test_text_chunks_hard_limit_aborts_execution(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="entrada.txt", mime_type="text/plain")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(FakeProviderClient(modes=["success", "success", "success"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "A" * 400)
    monkeypatch.setattr(execution_module.settings, "chunk_size_characters", 100)
    monkeypatch.setattr(execution_module.settings, "max_input_characters", 400)
    monkeypatch.setattr(execution_module.settings, "max_text_chunks_hard_limit", 2)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.FAILED.value
    assert "hard limit of text chunks" in (queue_repo.jobs[queue_job.id].error_message or "").lower()
    assert len(provider_service.client.execute_calls) == 0


def test_execution_rows_hard_limit_aborts_tabular_execution(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="input.csv")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(FakeProviderClient(modes=["success", "success", "success"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    csv_payload = "conteudo\nlinha 1\nlinha 2\nlinha 3\n".encode("utf-8")
    monkeypatch.setattr(service, "_read_input_file_bytes", lambda **_: csv_payload)
    monkeypatch.setattr(execution_module.settings, "max_execution_rows_hard_limit", 2)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.FAILED.value
    assert "hard limit of tabular rows" in (queue_repo.jobs[queue_job.id].error_message or "").lower()
    assert len(provider_service.client.execute_calls) == 0


def test_provider_calls_hard_limit_aborts_tabular_execution(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="input.csv")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(FakeProviderClient(modes=["success", "success", "success"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    csv_payload = "conteudo\nlinha 1\nlinha 2\nlinha 3\n".encode("utf-8")
    monkeypatch.setattr(service, "_read_input_file_bytes", lambda **_: csv_payload)
    monkeypatch.setattr(execution_module.settings, "max_provider_calls_hard_limit", 1)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.FAILED.value
    assert "hard limit of provider calls" in (queue_repo.jobs[queue_job.id].error_message or "").lower()
    assert len(provider_service.client.execute_calls) == 1


def test_tabular_row_size_hard_limit_aborts_execution(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="input.csv")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(FakeProviderClient(modes=["success"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    csv_payload = "conteudo,campo\nlinha muito grande para o limite hard,valor adicional\n".encode("utf-8")
    monkeypatch.setattr(service, "_read_input_file_bytes", lambda **_: csv_payload)
    monkeypatch.setattr(execution_module.settings, "max_tabular_row_characters_hard_limit", 10)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.FAILED.value
    assert "row exceeded hard character limit" in (queue_repo.jobs[queue_job.id].error_message or "").lower()
    assert len(provider_service.client.execute_calls) == 0


def test_execution_time_hard_limit_aborts_execution(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="entrada.txt", mime_type="text/plain")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(FakeProviderClient(modes=["success"]))
    service.provider_service = provider_service  # type: ignore[assignment]
    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "conteudo basico")
    monkeypatch.setattr(execution_module.settings, "max_execution_seconds_hard_limit", 10)

    timeline = [0.0, 20.0, 20.1, 20.2]

    def _fake_perf_counter() -> float:
        return timeline.pop(0) if timeline else 20.3

    monkeypatch.setattr(execution_module, "perf_counter", _fake_perf_counter)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.FAILED.value
    assert "hard processing time limit" in (queue_repo.jobs[queue_job.id].error_message or "").lower()
    assert len(provider_service.client.execute_calls) == 0


def test_job_retries_hard_limit_marks_execution_failed(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="entrada.txt", mime_type="text/plain")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(FakeProviderClient(modes=["timeout"]))
    service.provider_service = provider_service  # type: ignore[assignment]
    monkeypatch.setattr(service, "_read_input_file_content", lambda **_: "conteudo basico")
    monkeypatch.setattr(execution_module.settings, "max_retries", 10)
    monkeypatch.setattr(execution_module.settings, "max_job_retries_hard_limit", 1)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
        retry_count=1,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.FAILED.value
    assert "hard retry limit" in (queue_repo.jobs[queue_job.id].error_message or "").lower()


def test_execution_profile_uses_default_when_no_override(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="entrada.txt", mime_type="text/plain")
    service, _, _ = _build_service(analysis_request_id, automation_id, request_file)

    monkeypatch.setattr(execution_module.settings, "execution_profile_default", "standard")
    monkeypatch.setattr(execution_module.settings, "execution_profile_automation_overrides", {})
    monkeypatch.setattr(execution_module.settings, "execution_profile_standard_max_execution_rows", 25000)
    monkeypatch.setattr(execution_module.settings, "max_execution_rows_hard_limit", 100000)

    resolved = service._resolve_execution_profile(automation_id=automation_id)
    assert resolved.name == "standard"
    assert resolved.source == "env_default"
    assert resolved.max_execution_rows == 25000


def test_execution_profile_can_be_overridden_by_automation(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="entrada.txt", mime_type="text/plain")
    service, _, _ = _build_service(analysis_request_id, automation_id, request_file)

    monkeypatch.setattr(execution_module.settings, "execution_profile_default", "standard")
    monkeypatch.setattr(
        execution_module.settings,
        "execution_profile_automation_overrides",
        {str(automation_id).lower(): "heavy"},
    )

    resolved = service._resolve_execution_profile(automation_id=automation_id)
    assert resolved.name == "heavy"
    assert resolved.source == "env_automation_override"


def test_execution_profile_limits_are_clamped_by_hard_limits(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="entrada.txt", mime_type="text/plain")
    service, _, _ = _build_service(analysis_request_id, automation_id, request_file)

    monkeypatch.setattr(execution_module.settings, "execution_profile_default", "extended")
    monkeypatch.setattr(execution_module.settings, "execution_profile_extended_max_execution_rows", 250000)
    monkeypatch.setattr(execution_module.settings, "max_execution_rows_hard_limit", 100000)

    resolved = service._resolve_execution_profile(automation_id=automation_id)
    assert resolved.max_execution_rows == 100000
    assert "max_execution_rows" in resolved.hard_clamped_fields


def test_profile_rows_limit_can_abort_before_hard_limit(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="input.csv")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(FakeProviderClient(modes=["success", "success", "success"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    csv_payload = "conteudo\nlinha 1\nlinha 2\nlinha 3\n".encode("utf-8")
    monkeypatch.setattr(service, "_read_input_file_bytes", lambda **_: csv_payload)
    monkeypatch.setattr(execution_module.settings, "execution_profile_default", "standard")
    monkeypatch.setattr(execution_module.settings, "execution_profile_automation_overrides", {})
    monkeypatch.setattr(execution_module.settings, "execution_profile_standard_max_execution_rows", 2)
    monkeypatch.setattr(execution_module.settings, "max_execution_rows_hard_limit", 100000)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.FAILED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.FAILED.value
    assert "profile limit of tabular rows" in (queue_repo.jobs[queue_job.id].error_message or "").lower()
    assert len(provider_service.client.execute_calls) == 0


def test_automation_override_profile_allows_heavier_tabular_workload(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="input.csv")
    service, queue_repo, shared_exec_repo = _build_service(analysis_request_id, automation_id, request_file)
    provider_service = FakeProviderService(FakeProviderClient(modes=["success", "success", "success"]))
    service.provider_service = provider_service  # type: ignore[assignment]

    csv_payload = "conteudo\nlinha 1\nlinha 2\nlinha 3\n".encode("utf-8")
    monkeypatch.setattr(service, "_read_input_file_bytes", lambda **_: csv_payload)
    monkeypatch.setattr(execution_module.settings, "execution_profile_default", "standard")
    monkeypatch.setattr(
        execution_module.settings,
        "execution_profile_automation_overrides",
        {str(automation_id).lower(): "heavy"},
    )
    monkeypatch.setattr(execution_module.settings, "execution_profile_standard_max_execution_rows", 2)
    monkeypatch.setattr(execution_module.settings, "execution_profile_heavy_max_execution_rows", 10)
    monkeypatch.setattr(execution_module.settings, "max_execution_rows_hard_limit", 100000)

    execution, queue_job = _seed_execution_and_job(
        shared_exec_repo=shared_exec_repo,
        queue_repo=queue_repo,
        analysis_request_id=analysis_request_id,
        request_file_id=request_file.id,
    )
    service.process_execution_job(execution_id=execution.id, queue_job_id=queue_job.id, worker_name="worker")

    assert shared_exec_repo.executions[execution.id].status == ExecutionStatus.COMPLETED.value
    assert queue_repo.jobs[queue_job.id].job_status == ExecutionStatus.COMPLETED.value
    assert len(provider_service.client.execute_calls) == 3


def test_persisted_profile_has_precedence_over_env_override(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="entrada.txt", mime_type="text/plain")
    service, _, _ = _build_service(analysis_request_id, automation_id, request_file)

    monkeypatch.setattr(execution_module.settings, "execution_profile_default", "standard")
    monkeypatch.setattr(
        execution_module.settings,
        "execution_profile_automation_overrides",
        {str(automation_id).lower(): "extended"},
    )
    monkeypatch.setattr(execution_module.settings, "execution_profile_heavy_max_execution_rows", 33333)

    persisted = DjangoAiAutomationExecutionSetting(
        id=uuid4(),
        automation_id=automation_id,
        execution_profile="heavy",
        is_active=True,
    )
    service.execution_profile_settings.active_settings[automation_id] = persisted  # type: ignore[attr-defined]

    resolved = service._resolve_execution_profile(automation_id=automation_id)

    assert resolved.name == "heavy"
    assert resolved.source == "persisted_automation"
    assert resolved.max_execution_rows == 33333
    assert resolved.source_details["origin"] == "persisted_automation"


def test_persisted_profile_override_is_applied_and_hard_clamped(monkeypatch) -> None:
    analysis_request_id = uuid4()
    automation_id = uuid4()
    request_file = _build_request_file(analysis_request_id, file_name="entrada.txt", mime_type="text/plain")
    service, _, _ = _build_service(analysis_request_id, automation_id, request_file)

    monkeypatch.setattr(execution_module.settings, "execution_profile_default", "standard")
    monkeypatch.setattr(execution_module.settings, "execution_profile_standard_max_execution_rows", 25000)
    monkeypatch.setattr(execution_module.settings, "max_execution_rows_hard_limit", 100000)

    persisted = DjangoAiAutomationExecutionSetting(
        id=uuid4(),
        automation_id=automation_id,
        execution_profile="standard",
        is_active=True,
        max_execution_rows=120000,
    )
    service.execution_profile_settings.active_settings[automation_id] = persisted  # type: ignore[attr-defined]

    resolved = service._resolve_execution_profile(automation_id=automation_id)

    assert resolved.source == "persisted_automation"
    assert resolved.persisted_overrides["max_execution_rows"] == 120000
    assert resolved.max_execution_rows == 100000
    assert "max_execution_rows" in resolved.hard_clamped_fields
