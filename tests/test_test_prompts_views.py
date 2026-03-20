import importlib
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


def test_create_view_saves_prompt_using_runtime_automation_when_available(monkeypatch) -> None:
    automation_id = uuid4()
    saved_payload: dict[str, object] = {}

    monkeypatch.setattr(
        "test_prompts.views._load_test_prompt_runtime_payload",
        lambda: (
            SimpleNamespace(
                automation_id=automation_id,
                automation_name="Automacao Tecnica de Teste",
                automation_slug="system-test-automation",
                analysis_request_id=uuid4(),
            ),
            "api",
            [],
        ),
    )

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
    assert saved_payload["automation_id"] == automation_id


def test_execution_create_view_uses_test_prompt_execution_endpoint(monkeypatch) -> None:
    called: dict[str, object] = {}
    execution_id = uuid4()
    prompt_pk = 101

    class FakeService:
        def start_test_prompt_execution(self, *, uploaded_file, prompt_override):  # type: ignore[no-untyped-def]
            called["uploaded_file"] = uploaded_file
            called["prompt_override"] = prompt_override
            return SimpleNamespace(execution_id=execution_id)

    monkeypatch.setattr("test_prompts.views.AutomationPromptsExecutionService", lambda: FakeService())

    request = RequestFactory().post("/prompts-teste/101/executar/")
    request.user = SimpleNamespace(is_authenticated=True)
    request.session = {}
    request._messages = FallbackStorage(request)

    view = test_prompt_views.TestPromptExecutionCreateView()
    view.setup(request, pk=prompt_pk)
    view.test_prompt = SimpleNamespace(pk=prompt_pk, prompt_text="Prompt local override")

    form = SimpleNamespace(cleaned_data={"request_file": object()})  # type: ignore[assignment]
    response = view.form_valid(form)

    assert response.status_code == 302
    assert called["prompt_override"] == "Prompt local override"
    assert str(execution_id) in response.url
