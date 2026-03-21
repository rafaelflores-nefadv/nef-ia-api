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
    def __init__(self, *, runtime: object | None) -> None:
        self.runtime = runtime

    def get_automation_by_id(self, automation_id):  # type: ignore[no-untyped-def]
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


def _build_service(*, automation_id, runtime):  # type: ignore[no-untyped-def]
    service = AdminAutomationExecutionService(
        operational_session=FakeSession(),  # type: ignore[arg-type]
        shared_session=FakeSession(),  # type: ignore[arg-type]
    )
    service.shared_automations = FakeSharedAutomations(runtime=runtime)  # type: ignore[assignment]
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
    analysis_request_id = uuid4()
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
            analysis_request_id=analysis_request_id,
        )
    )

    result = service.create_test_automation(
        name="Teste OCR",
        provider_id=provider_id,
        model_id=model_id,
    )

    assert result["automation_id"] == automation_id
    assert result["analysis_request_id"] == analysis_request_id
    assert result["provider_slug"] == "openai"
    assert result["model_slug"] == "gpt-4.1-mini"


def test_admin_get_prompt_test_runtime_reads_technical_context() -> None:
    automation_id = uuid4()
    analysis_request_id = uuid4()
    service = _build_service(automation_id=automation_id, runtime=None)
    service.test_prompt_runtime = SimpleNamespace(  # type: ignore[assignment]
        ensure_runtime_context=lambda: SimpleNamespace(
            automation_id=automation_id,
            automation_name="Automacao Tecnica de Teste",
            automation_slug="system-test-automation",
            provider_slug="openai",
            model_slug="gpt-4.1-mini",
            analysis_request_id=analysis_request_id,
        )
    )

    payload = service.get_prompt_test_runtime()

    assert payload["automation_id"] == automation_id
    assert payload["analysis_request_id"] == analysis_request_id
    assert payload["provider_slug"] == "openai"
    assert payload["model_slug"] == "gpt-4.1-mini"
    assert payload["is_test_automation"] is True
