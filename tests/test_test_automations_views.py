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
from django.urls import reverse

from test_automations import views as test_automation_views


def test_create_view_creates_test_automation_via_separated_service(monkeypatch) -> None:
    called: dict[str, object] = {}
    automation_id = uuid4()

    class FakeService:
        def create_test_automation(self, *, name, provider_id, model_id):  # type: ignore[no-untyped-def]
            called["name"] = name
            called["provider_id"] = provider_id
            called["model_id"] = model_id
            return SimpleNamespace(automation_id=automation_id)

    monkeypatch.setattr("test_automations.views.AutomationPromptsExecutionService", lambda: FakeService())

    request = RequestFactory().post("/automacoes-teste/nova/")
    request.user = SimpleNamespace(is_authenticated=True)
    request.session = {}
    request._messages = FallbackStorage(request)

    view = test_automation_views.TestAutomationCreateView()
    view.setup(request)

    provider_id = uuid4()
    model_id = uuid4()
    form = SimpleNamespace(  # type: ignore[assignment]
        cleaned_data={
            "name": "OCR financeiro",
            "provider_id": str(provider_id),
            "model_id": str(model_id),
            "is_active": True,
        },
        add_error=lambda *args, **kwargs: None,
    )

    response = view.form_valid(form)

    assert response.status_code == 302
    assert response.url == reverse("test_automations:list")
    assert called == {
        "name": "OCR financeiro",
        "provider_id": provider_id,
        "model_id": model_id,
    }


def test_delete_view_removes_test_automation_from_separated_area(monkeypatch) -> None:
    automation_id = uuid4()
    deleted: list[object] = []

    class FakeService:
        def get_test_automation(self, *, automation_id):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                automation_id=automation_id,
                automation_name="Teste OCR",
            )

        def delete_test_automation(self, *, automation_id):  # type: ignore[no-untyped-def]
            deleted.append(automation_id)

    monkeypatch.setattr("test_automations.views.AutomationPromptsExecutionService", lambda: FakeService())

    request = RequestFactory().post(f"/automacoes-teste/{automation_id}/excluir/")
    request.user = SimpleNamespace(is_authenticated=True)
    request.session = {}
    request._messages = FallbackStorage(request)

    response = test_automation_views.TestAutomationDeleteView.as_view()(request, automation_id=automation_id)

    assert response.status_code == 302
    assert response.url == reverse("test_automations:list")
    assert deleted == [automation_id]


def test_provider_models_view_returns_json_from_test_automation_area(monkeypatch) -> None:
    provider_id = uuid4()
    model_id = uuid4()

    class FakeService:
        def list_provider_models(self, *, provider_id):  # type: ignore[no-untyped-def]
            return [
                SimpleNamespace(
                    id=model_id,
                    provider_id=provider_id,
                    model_name="GPT 4.1 Mini",
                    model_slug="gpt-4.1-mini",
                )
            ]

    monkeypatch.setattr("test_automations.views.AutomationPromptsExecutionService", lambda: FakeService())

    request = RequestFactory().get(f"/automacoes-teste/modelos/?provider_id={provider_id}")
    request.user = SimpleNamespace(is_authenticated=True)

    response = test_automation_views.TestAutomationProviderModelsView.as_view()(request)
    payload = json.loads(response.content.decode("utf-8"))

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["items"][0]["id"] == str(model_id)
