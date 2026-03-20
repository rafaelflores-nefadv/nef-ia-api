import os
import importlib
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

from django.test import RequestFactory

from test_prompts import views as test_prompt_views


def test_create_view_get_form_kwargs_works_without_test_prompt(monkeypatch) -> None:
    automation_id = uuid4()

    monkeypatch.setattr(
        "test_prompts.views._load_automation_runtime_payload",
        lambda: (
            [SimpleNamespace(automation_id=automation_id, automation_name="Automacao A")],
            "api",
            [],
        ),
    )

    request = RequestFactory().get("/prompts-teste/novo/")
    view = test_prompt_views.TestPromptCreateView()
    view.setup(request)

    kwargs = view.get_form_kwargs()

    assert "automation_choices" in kwargs
    assert kwargs["automation_choices"] == [
        (automation_id, f"Automacao A ({automation_id})"),
    ]


def test_update_view_keeps_current_automation_when_runtime_is_empty(monkeypatch) -> None:
    current_automation_id = uuid4()

    monkeypatch.setattr(
        "test_prompts.views._load_automation_runtime_payload",
        lambda: ([], "unavailable", ["temporarily unavailable"]),
    )

    request = RequestFactory().get("/prompts-teste/1/editar/")
    view = test_prompt_views.TestPromptUpdateView()
    view.setup(request, pk=1)
    view.test_prompt = SimpleNamespace(
        name="Prompt X",
        automation_id=current_automation_id,
        prompt_text="Texto",
        notes="",
        is_active=True,
    )

    kwargs = view.get_form_kwargs()

    assert "automation_choices" in kwargs
    assert kwargs["automation_choices"] == [
        (
            current_automation_id,
            f"Automacao atual ({current_automation_id})",
        ),
    ]
