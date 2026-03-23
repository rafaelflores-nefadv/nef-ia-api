import os
import json
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.urls import reverse

from core.services.automation_prompts_execution_service import (
    AutomationExecutionFileItem,
    AutomationExecutionStatusItem,
)
from prompts.forms import AutomationExecutionForm
from prompts.views import AutomationExecutionDetailView, AutomationExecutionStatusView
from test_prompts.forms import TestPromptExecutionForm as PromptExecutionForm
from test_prompts.forms import TestPromptForm as PromptForm
from test_prompts.models import TestPrompt, TestPromptExecution
from test_prompts.views import TestPromptExecutionCreateView as PromptExecutionCreateView
from test_prompts.views import TestPromptExecutionDetailView as LocalExecutionDetailView
from test_prompts.views import TestPromptExecutionStatusView as LocalExecutionStatusView
from core.services.automation_prompts_execution_service import PromptTestExecutionStartItem


def _build_request(path: str, *, method: str = "GET"):
    factory = RequestFactory()
    if method == "POST":
        request = factory.post(path)
    else:
        request = factory.get(path)
    request.user = SimpleNamespace(is_authenticated=True)
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def test_execution_forms_do_not_expose_manual_automation_selection() -> None:
    prompt_execution_form = AutomationExecutionForm()
    test_prompt_execution_form = PromptExecutionForm()

    assert "automation" not in prompt_execution_form.fields
    assert "automation" not in test_prompt_execution_form.fields
    assert "request_file" in prompt_execution_form.fields
    assert "request_file" in test_prompt_execution_form.fields


def test_test_prompt_form_requires_linked_automation() -> None:
    automation_id = uuid4()
    form = PromptForm(
        data={
            "name": "Prompt teste",
            "automation_id": "",
            "prompt_text": "Texto",
            "notes": "",
            "is_active": "on",
        },
        automation_choices=[(automation_id, "Automacao A")],
    )

    assert form.is_valid() is False
    assert "automation_id" in form.errors


def test_execution_redirects_when_prompt_has_no_linked_automation(monkeypatch) -> None:
    prompt = SimpleNamespace(pk=7, automation_id=None)
    monkeypatch.setattr("test_prompts.views.get_object_or_404", lambda model, pk: prompt)

    request = _build_request("/prompts-teste/7/executar/")
    response = PromptExecutionCreateView.as_view()(request, pk=7)
    feedback = [str(item.message) for item in get_messages(request)]

    assert response.status_code == 302
    assert response.url == reverse("test_prompts:edit", kwargs={"pk": 7})
    assert any("nao possui automacao" in item.lower() for item in feedback)


def test_test_prompt_execution_uses_prompt_linked_automation(monkeypatch) -> None:
    linked_automation = SimpleNamespace(
        id=uuid4(),
        name="Auto Teste",
        provider_id=uuid4(),
        model_id=uuid4(),
        credential_id=uuid4(),
        provider_slug="openai",
        model_slug="gpt-4o-mini",
        credential_name="credencial-a",
        output_type="spreadsheet_output",
        result_parser="tabular_structured",
        result_formatter="spreadsheet_tabular",
        output_schema={"columns": ["linha_origem", "conteudo", "status"]},
        debug_enabled=True,
    )
    test_prompt = SimpleNamespace(pk=11, prompt_text="Prompt override")

    remote_execution_id = uuid4()
    captured = {"start_kwargs": None, "build_kwargs": None}

    class FakeService:
        def start_test_prompt_execution(self, **kwargs):  # type: ignore[no-untyped-def]
            captured["start_kwargs"] = kwargs
            return PromptTestExecutionStartItem(
                execution_id=remote_execution_id,
                status="queued",
                phase="queued",
                progress_percent=2,
                status_message="Execucao enfileirada.",
                is_terminal=False,
                created_at=datetime(2026, 3, 21, 10, 0, 0),
            )

    monkeypatch.setattr("test_prompts.views.AutomationPromptsExecutionService", lambda: FakeService())

    view = PromptExecutionCreateView()
    view.request = _build_request("/prompts-teste/11/executar/", method="POST")
    view.test_prompt = test_prompt
    view.linked_automation = linked_automation
    view._build_execution_record = lambda **kwargs: captured.update({"build_kwargs": kwargs}) or SimpleNamespace(id=uuid4())  # type: ignore[method-assign]

    uploaded = SimpleUploadedFile(
        "entrada.txt",
        b"conteudo",
        content_type="text/plain",
    )
    form = PromptExecutionForm(data={}, files={"request_file": uploaded})
    assert form.is_valid() is True

    response = view.form_valid(form)

    assert response.status_code == 302
    assert response.url.startswith("/prompts-teste/11/execucoes/")
    assert captured["start_kwargs"] is not None
    assert captured["start_kwargs"]["provider_id"] == linked_automation.provider_id
    assert captured["start_kwargs"]["model_id"] == linked_automation.model_id
    assert captured["start_kwargs"]["credential_id"] == linked_automation.credential_id
    assert captured["start_kwargs"]["prompt_override"] == "Prompt override"
    assert captured["start_kwargs"]["output_type"] == "spreadsheet_output"
    assert captured["start_kwargs"]["result_parser"] == "tabular_structured"
    assert captured["start_kwargs"]["result_formatter"] == "spreadsheet_tabular"
    assert captured["start_kwargs"]["output_schema"] == {"columns": ["linha_origem", "conteudo", "status"]}
    assert captured["start_kwargs"]["debug_enabled"] is True
    assert captured["build_kwargs"] is not None
    assert captured["build_kwargs"]["remote_start"].execution_id == remote_execution_id


def test_prompts_status_endpoint_returns_progress_and_files(monkeypatch) -> None:
    execution_id = uuid4()
    file_id = uuid4()

    class FakeService:
        def get_execution_status(self, *, execution_id):  # type: ignore[no-untyped-def]
            return AutomationExecutionStatusItem(
                execution_id=execution_id,
                analysis_request_id=uuid4(),
                automation_id=uuid4(),
                request_file_id=uuid4(),
                request_file_name="entrada.xlsx",
                prompt_override_applied=False,
                status="completed",
                progress=100,
                started_at=datetime(2026, 3, 21, 10, 0, 0),
                finished_at=datetime(2026, 3, 21, 10, 1, 0),
                error_message="",
                created_at=datetime(2026, 3, 21, 9, 59, 50),
                checked_at=datetime(2026, 3, 21, 10, 1, 1),
            )

        def list_execution_files(self, *, execution_id):  # type: ignore[no-untyped-def]
            return [
                AutomationExecutionFileItem(
                    id=file_id,
                    execution_id=execution_id,
                    file_type="result",
                    file_name="saida.xlsx",
                    file_path="/tmp/saida.xlsx",
                    file_size=2048,
                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    checksum="abc123",
                    created_at=datetime(2026, 3, 21, 10, 1, 2),
                )
            ]

    monkeypatch.setattr("prompts.views.AutomationPromptsExecutionService", lambda: FakeService())

    request = _build_request(f"/prompts/execucoes/{execution_id}/status/")
    response = AutomationExecutionStatusView.as_view()(request, execution_id=str(execution_id))
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["status"] == "completed"
    assert payload["progress_percent"] == 100
    assert payload["is_terminal"] is True
    assert len(payload["file_rows"]) == 1
    assert payload["file_rows"][0]["id"] == str(file_id)
    assert payload["file_rows"][0]["download_url"].endswith(f"/prompts/arquivos/{file_id}/download/")


def test_execution_detail_context_exposes_progress_and_status_message() -> None:
    execution_id = uuid4()
    view = AutomationExecutionDetailView()
    view.request = _build_request(f"/prompts/execucoes/{execution_id}/")
    view.kwargs = {"execution_id": str(execution_id)}
    view.execution_status = AutomationExecutionStatusItem(
        execution_id=execution_id,
        analysis_request_id=uuid4(),
        automation_id=uuid4(),
        request_file_id=uuid4(),
        request_file_name="entrada.xlsx",
        prompt_override_applied=False,
        status="processing",
        progress=None,
        started_at=None,
        finished_at=None,
        error_message="",
        created_at=None,
        checked_at=None,
    )
    view.execution_files = []
    view.integration_source = "api"
    view.integration_warnings = []

    context = view.get_context_data()

    assert context["progress_percent"] == 55
    assert "Processando" in context["status_message"]
    assert context["status_endpoint_url"].endswith(f"/prompts/execucoes/{execution_id}/status/")


def test_test_prompt_execution_status_endpoint_returns_progress_and_download_url(monkeypatch) -> None:
    prompt = SimpleNamespace(pk=11)
    execution_id = uuid4()
    execution = SimpleNamespace(
        id=execution_id,
        status=TestPromptExecution.STATUS_COMPLETED,
        error_message="",
        remote_error_message="",
        remote_execution_id=None,
        remote_status="completed",
        remote_phase="completed",
        remote_progress_percent=100,
        remote_status_message="Concluida.",
        remote_result_ready=True,
        result_type=TestPromptExecution.RESULT_FILE,
        output_text="",
        output_file_name="saida.xlsx",
        output_file_mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        output_file_size=2048,
        output_file_content=b"abc",
        request_file_name="entrada.xlsx",
    )

    def _fake_get_object_or_404(model, **kwargs):  # type: ignore[no-untyped-def]
        if model is TestPrompt:
            return prompt
        return execution

    monkeypatch.setattr("test_prompts.views.get_object_or_404", _fake_get_object_or_404)

    request = _build_request(f"/prompts-teste/11/execucoes/{execution_id}/status/")
    response = LocalExecutionStatusView.as_view()(request, pk=11, execution_id=str(execution_id))
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["status"] == "completed"
    assert payload["progress_percent"] == 100
    assert payload["is_terminal"] is True
    assert payload["output_download_url"].endswith(f"/prompts-teste/11/execucoes/{execution_id}/arquivo/")


def test_test_prompt_execution_detail_context_exposes_polling_data() -> None:
    execution_id = uuid4()
    view = LocalExecutionDetailView()
    view.request = _build_request(f"/prompts-teste/11/execucoes/{execution_id}/")
    view.kwargs = {"pk": 11, "execution_id": str(execution_id)}
    view.test_prompt = SimpleNamespace(pk=11, name="Prompt X")
    view.execution = SimpleNamespace(
        id=execution_id,
        status=TestPromptExecution.STATUS_RUNNING,
        error_message="",
        remote_error_message="",
        remote_execution_id=None,
        remote_status="running",
        remote_phase="running_model",
        remote_progress_percent=42,
        remote_status_message="Executando modelo.",
        result_type=TestPromptExecution.RESULT_TEXT,
        output_file_content=None,
        output_file_name="",
        output_file_mime_type="",
        output_file_size=0,
        request_file_size=1024,
        output_text="",
    )

    context = view.get_context_data()

    assert context["progress_percent"] == 42
    assert context["is_terminal"] is False
    assert context["phase"] == "running_model"
    assert context["status_endpoint_url"].endswith(f"/prompts-teste/11/execucoes/{execution_id}/status/")


def test_test_prompt_execution_status_uses_remote_progress_without_fake_mapping(monkeypatch) -> None:
    prompt = SimpleNamespace(pk=11)
    execution_id = uuid4()
    execution = SimpleNamespace(
        id=execution_id,
        status=TestPromptExecution.STATUS_RUNNING,
        error_message="",
        remote_error_message="",
        remote_execution_id=None,
        remote_status="running",
        remote_phase="running_model",
        remote_progress_percent=37,
        remote_status_message="Executando modelo.",
        remote_result_ready=False,
        result_type=TestPromptExecution.RESULT_TEXT,
        output_text="",
        output_file_name="",
        output_file_mime_type="",
        output_file_size=0,
        output_file_content=None,
        request_file_name="entrada.xlsx",
    )

    def _fake_get_object_or_404(model, **kwargs):  # type: ignore[no-untyped-def]
        if model is TestPrompt:
            return prompt
        return execution

    monkeypatch.setattr("test_prompts.views.get_object_or_404", _fake_get_object_or_404)

    request = _build_request(f"/prompts-teste/11/execucoes/{execution_id}/status/")
    response = LocalExecutionStatusView.as_view()(request, pk=11, execution_id=str(execution_id))
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["status"] == "running"
    assert payload["progress_percent"] == 37
    assert payload["phase"] == "running_model"
