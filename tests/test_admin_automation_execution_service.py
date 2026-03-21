from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.constants import ExecutionStatus
from app.core.exceptions import AppException
from app.services.admin_automation_execution_service import AdminAutomationExecutionService


class FakeSession:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class FakeSharedAutomations:
    def __init__(self, *, runtime: object | None, official_automation_ids: set | None = None) -> None:  # type: ignore[type-arg]
        self.runtime = runtime
        self.official_automation_ids = official_automation_ids or set()

    def get_automation_by_id(self, automation_id):  # type: ignore[no-untyped-def]
        if automation_id not in self.official_automation_ids:
            return None
        return SimpleNamespace(id=automation_id, is_active=True, name="Automacao X")

    def get_runtime_config_for_automation(self, automation_id):  # type: ignore[no-untyped-def]
        return self.runtime

    def get_runtime_target_for_automation(self, automation_id):  # type: ignore[no-untyped-def]
        return self.runtime


class FakeSharedAnalysis:
    def __init__(self, *, automation_id) -> None:  # type: ignore[no-untyped-def]
        self.latest_request = SimpleNamespace(
            id=uuid4(),
            automation_id=automation_id,
            created_at=datetime.now(timezone.utc),
        )

    def get_latest_request_by_automation_id(self, automation_id):  # type: ignore[no-untyped-def]
        if self.latest_request.automation_id != automation_id:
            return None
        return self.latest_request

    def get_request_by_id(self, analysis_request_id):  # type: ignore[no-untyped-def]
        if self.latest_request.id != analysis_request_id:
            return None
        return self.latest_request


class FakeFileService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.request_file_id = uuid4()

    def upload_request_file(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return SimpleNamespace(id=self.request_file_id)


class FakeExecutionService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.execution_id = uuid4()
        self.queue_job_id = uuid4()

    def create_execution(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return SimpleNamespace(
            execution_id=self.execution_id,
            queue_job_id=self.queue_job_id,
            status=ExecutionStatus.QUEUED,
        )


def _build_service(*, automation_id, runtime, official_automation_ids=None):  # type: ignore[no-untyped-def]
    service = AdminAutomationExecutionService(
        operational_session=FakeSession(),  # type: ignore[arg-type]
        shared_session=FakeSession(),  # type: ignore[arg-type]
    )
    service.shared_automations = FakeSharedAutomations(  # type: ignore[assignment]
        runtime=runtime,
        official_automation_ids=official_automation_ids or {automation_id},
    )
    service.shared_analysis = FakeSharedAnalysis(automation_id=automation_id)  # type: ignore[assignment]
    service.file_service = FakeFileService()  # type: ignore[assignment]
    service.execution_service = FakeExecutionService()  # type: ignore[assignment]
    return service


def test_admin_execution_allows_prompt_override_without_official_prompt() -> None:
    automation_id = uuid4()
    service = _build_service(automation_id=automation_id, runtime=None)

    result = service.start_execution_for_automation(
        automation_id=automation_id,
        upload_file=SimpleNamespace(filename="input.csv"),
        prompt_override="  Prompt override para execucao  ",
        actor_user_id=uuid4(),
        ip_address="127.0.0.1",
        correlation_id="corr-1",
    )

    assert result.status == ExecutionStatus.QUEUED
    assert result.prompt_override_applied is True
    assert result.prompt_version == 0
    assert service.execution_service.calls  # type: ignore[attr-defined]
    assert service.execution_service.calls[0]["prompt_override"] == "Prompt override para execucao"  # type: ignore[index]


def test_admin_execution_requires_official_prompt_when_override_missing() -> None:
    automation_id = uuid4()
    service = _build_service(automation_id=automation_id, runtime=None)

    with pytest.raises(AppException) as exc:
        service.start_execution_for_automation(
            automation_id=automation_id,
            upload_file=SimpleNamespace(filename="input.csv"),
            prompt_override=None,
            actor_user_id=uuid4(),
            ip_address="127.0.0.1",
            correlation_id="corr-2",
        )

    assert exc.value.payload.code == "prompt_not_found"


def test_admin_create_test_automation_uses_selected_provider_model() -> None:
    automation_id = uuid4()
    provider_id = uuid4()
    model_id = uuid4()
    service = _build_service(automation_id=uuid4(), runtime=None)
    service.providers = SimpleNamespace(  # type: ignore[assignment]
        get_by_id=lambda current_provider_id: (
            SimpleNamespace(id=provider_id, slug="openai", is_active=True, name="OpenAI")
            if current_provider_id == provider_id
            else None
        )
    )
    service.provider_models = SimpleNamespace(  # type: ignore[assignment]
        get_by_id=lambda current_model_id: (
            SimpleNamespace(
                id=model_id,
                provider_id=provider_id,
                model_slug="gpt-4.1-mini",
                is_active=True,
            )
            if current_model_id == model_id
            else None
        )
    )
    service.test_prompt_runtime = SimpleNamespace(  # type: ignore[assignment]
        create_manual_test_automation=lambda **_: SimpleNamespace(
            automation_id=automation_id,
            automation_name="Teste OCR",
            automation_slug="test-prompt-ocr",
            provider_slug="openai",
            model_slug="gpt-4.1-mini",
        )
    )

    result = service.create_test_automation(
        name="Teste OCR",
        provider_id=provider_id,
        model_id=model_id,
    )

    assert result["automation_id"] == automation_id
    assert result["provider_slug"] == "openai"
    assert result["model_slug"] == "gpt-4.1-mini"


def test_admin_get_prompt_test_runtime_reads_technical_context() -> None:
    automation_id = uuid4()
    shared_automation_id = uuid4()
    analysis_request_id = uuid4()
    service = _build_service(automation_id=automation_id, runtime=None)
    service.test_prompt_runtime = SimpleNamespace(  # type: ignore[assignment]
        ensure_runtime_context=lambda: SimpleNamespace(
            automation_id=automation_id,
            automation_name="Automacao Tecnica de Teste",
            automation_slug="system-test-automation",
            shared_automation_id=shared_automation_id,
            analysis_request_id=analysis_request_id,
        )
    )

    payload = service.get_prompt_test_runtime()

    assert payload["technical_automation_id"] == automation_id
    assert payload["shared_automation_id"] == shared_automation_id
    assert payload["analysis_request_id"] == analysis_request_id
    assert payload["is_test_automation"] is True


def test_admin_execution_with_test_automation_uses_technical_request_and_test_context() -> None:
    technical_automation_id = uuid4()
    test_automation_id = uuid4()
    analysis_request_id = uuid4()
    service = _build_service(
        automation_id=technical_automation_id,
        runtime=None,
        official_automation_ids={technical_automation_id},
    )
    service.shared_automations = FakeSharedAutomations(  # type: ignore[assignment]
        runtime=None,
        official_automation_ids={technical_automation_id},
    )
    service.test_prompt_runtime = SimpleNamespace(  # type: ignore[assignment]
        get_execution_target_for_test_automation=lambda automation_id: SimpleNamespace(
            test_automation_id=automation_id,
            test_automation_name="Teste OCR",
            test_automation_slug="test-prompt-ocr",
            provider_slug="openai",
            model_slug="gpt-4.1-mini",
            shared_automation_id=technical_automation_id,
            analysis_request_id=analysis_request_id,
        )
    )
    service.shared_analysis.latest_request = SimpleNamespace(  # type: ignore[attr-defined]
        id=analysis_request_id,
        automation_id=technical_automation_id,
        created_at=datetime.now(timezone.utc),
    )

    result = service.start_execution_for_automation(
        automation_id=test_automation_id,
        upload_file=SimpleNamespace(filename="input.csv"),
        prompt_override="override teste",
        actor_user_id=uuid4(),
        ip_address="127.0.0.1",
        correlation_id="corr-test",
    )

    assert result.automation_id == test_automation_id
    assert service.execution_service.calls[0]["analysis_request_id"] == analysis_request_id  # type: ignore[index]
    context = service.execution_service.calls[0]["prompt_test_context"]  # type: ignore[index]
    assert context.test_automation_id == test_automation_id
    assert context.provider_slug == "openai"
