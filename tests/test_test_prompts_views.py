import importlib
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
project_settings = importlib.import_module("config.settings")
project_settings.DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
django.setup()

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from test_prompts import forms as test_prompt_forms
from test_prompts import views as test_prompt_views


def test_test_prompt_form_no_longer_exposes_automation_field() -> None:
    form = test_prompt_forms.TestPromptForm()
    assert "automation" not in form.fields


def test_create_view_saves_prompt_without_runtime_automation(monkeypatch) -> None:
    saved_payload: dict[str, object] = {}

    class FakePrompt:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            saved_payload.update(kwargs)

        def save(self):  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setattr("test_prompts.views.TestPrompt", FakePrompt)

    request = RequestFactory().post("/prompts-teste/novo/")
    request.user = SimpleNamespace(is_authenticated=True)
    request.session = {}
    request._messages = FallbackStorage(request)

    view = test_prompt_views.TestPromptCreateView()
    view.setup(request)

    form = SimpleNamespace(  # type: ignore[assignment]
        cleaned_data={
            "name": "Prompt teste",
            "prompt_text": "Texto de override",
            "notes": "obs",
            "is_active": True,
        }
    )
    response = view.form_valid(form)

    assert response.status_code == 302
    assert saved_payload["automation_id"] is None


def test_execution_create_view_uses_selected_automation(monkeypatch) -> None:
    called: dict[str, object] = {}
    execution_id = uuid4()
    automation_id = uuid4()
    prompt_pk = 101
    save_updates: list[list[str]] = []

    class FakeService:
        def start_execution(self, *, automation_id, uploaded_file, prompt_override):  # type: ignore[no-untyped-def]
            called["automation_id"] = automation_id
            called["uploaded_file"] = uploaded_file
            called["prompt_override"] = prompt_override
            return SimpleNamespace(execution_id=execution_id)

    class FakePrompt:
        def __init__(self):  # type: ignore[no-untyped-def]
            self.pk = prompt_pk
            self.prompt_text = "Prompt local override"
            self.automation_id = None

        def save(self, update_fields):  # type: ignore[no-untyped-def]
            save_updates.append(update_fields)

    monkeypatch.setattr("test_prompts.views.AutomationPromptsExecutionService", lambda: FakeService())

    request = RequestFactory().post("/prompts-teste/101/executar/")
    request.user = SimpleNamespace(is_authenticated=True)
    request.session = {}
    request._messages = FallbackStorage(request)

    view = test_prompt_views.TestPromptExecutionCreateView()
    view.setup(request, pk=prompt_pk)
    view.test_prompt = FakePrompt()

    form = SimpleNamespace(cleaned_data={"automation": str(automation_id), "request_file": object()})  # type: ignore[assignment]
    response = view.form_valid(form)

    assert response.status_code == 302
    assert called["automation_id"] == automation_id
    assert called["prompt_override"] == "Prompt local override"
    assert str(execution_id) in response.url
    assert save_updates


def test_test_automation_create_view_returns_created_payload(monkeypatch) -> None:
    automation_id = uuid4()
    analysis_request_id = uuid4()

    class FakeService:
        def create_test_automation(self, *, name, provider_id, model_id):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                automation_id=automation_id,
                automation_name=name,
                automation_slug="test-prompt-exemplo",
                analysis_request_id=analysis_request_id,
                provider_slug="openai",
                model_slug="gpt-4.1-mini",
                is_test_automation=True,
            )

    monkeypatch.setattr("test_prompts.views.AutomationPromptsExecutionService", lambda: FakeService())

    request = RequestFactory().post(
        "/prompts-teste/automacoes/criar/",
        data={
            "name": "Teste planilhas",
            "provider_id": str(uuid4()),
            "model_id": str(uuid4()),
        },
    )
    request.user = SimpleNamespace(is_authenticated=True)

    response = test_prompt_views.TestAutomationCreateView.as_view()(request)
    payload = json.loads(response.content.decode("utf-8"))

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["automation"]["automation_id"] == str(automation_id)
