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
from django.urls import reverse

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


def test_load_test_automation_payload_returns_real_list(monkeypatch) -> None:
    automation_id = uuid4()

    class FakeService:
        def list_test_automations(self, *, active_only=True):  # type: ignore[no-untyped-def]
            assert active_only is True
            return [
                SimpleNamespace(
                    automation_id=automation_id,
                    automation_name="Teste real",
                    automation_slug="teste-real",
                    provider_slug="openai",
                    model_slug="gpt-4.1-mini",
                    is_active=True,
                    is_test_automation=True,
                )
            ]

    monkeypatch.setattr("test_prompts.views.AutomationPromptsExecutionService", lambda: FakeService())

    items, source, warnings = test_prompt_views._load_test_automation_payload(active_only=True)

    assert source == "api"
    assert warnings == []
    assert len(items) == 1
    assert items[0].automation_id == automation_id


def test_execution_view_context_uses_separated_automation_urls() -> None:
    prompt = SimpleNamespace(pk=42, name="Prompt local", prompt_text="Texto")
    automation = SimpleNamespace(
        automation_id=uuid4(),
        automation_name="Teste real",
        provider_slug="openai",
        model_slug="gpt-4.1-mini",
    )

    request = RequestFactory().get("/prompts-teste/42/executar/")
    request.user = SimpleNamespace(is_authenticated=True)

    view = test_prompt_views.TestPromptExecutionCreateView()
    view.setup(request, pk=42)
    view.test_prompt = prompt
    view.test_automations = [automation]
    view.technical_runtime = None
    view.integration_source = "api"
    view.integration_warnings = []
    view.object = None
    form = test_prompt_forms.TestPromptExecutionForm(
        automation_choices=[(automation.automation_id, automation.automation_name)],
        selected_automation=str(automation.automation_id),
    )

    context = view.get_context_data(form=form)

    assert context["automation_management_url"] == reverse("test_automations:list")
    assert context["automation_create_url"] == reverse("test_automations:create")


def test_prompt_delete_view_removes_prompt_and_redirects(monkeypatch) -> None:
    deleted: list[bool] = []
    prompt = SimpleNamespace(pk=7, name="Prompt legado", delete=lambda: deleted.append(True))

    monkeypatch.setattr("test_prompts.views.get_object_or_404", lambda *args, **kwargs: prompt)

    request = RequestFactory().post("/prompts-teste/7/excluir/")
    request.user = SimpleNamespace(is_authenticated=True)
    request.session = {}
    request._messages = FallbackStorage(request)

    response = test_prompt_views.TestPromptDeleteView.as_view()(request, pk=7)

    assert response.status_code == 302
    assert response.url == reverse("test_prompts:list")
    assert deleted == [True]
