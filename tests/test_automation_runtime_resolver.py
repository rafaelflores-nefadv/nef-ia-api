from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import AppException
from app.services.shared.automation_runtime_resolver import AutomationRuntimeResolverService


class FakeRepository:
    def __init__(self, *, runtime_record: object | None, runtime_target: object | None) -> None:
        self.runtime_record = runtime_record
        self.runtime_target = runtime_target
        self.automation = None

    def get_automation_by_id(self, automation_id):  # type: ignore[no-untyped-def]
        self.automation = SimpleNamespace(id=automation_id, name="Automacao", is_active=True)
        return self.automation

    def get_runtime_config_for_automation(self, automation_id):  # type: ignore[no-untyped-def]
        return self.runtime_record

    def get_runtime_target_for_automation(self, automation_id):  # type: ignore[no-untyped-def]
        return self.runtime_target


def test_runtime_resolver_requires_prompt_by_default() -> None:
    automation_id = uuid4()
    resolver = AutomationRuntimeResolverService(shared_session=SimpleNamespace())  # type: ignore[arg-type]
    resolver.repository = FakeRepository(runtime_record=None, runtime_target=None)  # type: ignore[assignment]

    with pytest.raises(AppException) as exc:
        resolver.resolve(automation_id)

    assert exc.value.payload.code == "prompt_not_found"


def test_runtime_resolver_uses_runtime_target_when_prompt_is_not_required() -> None:
    automation_id = uuid4()
    runtime_target = SimpleNamespace(
        automation_id=automation_id,
        provider_slug="openai",
        model_slug="gpt-5",
    )
    resolver = AutomationRuntimeResolverService(shared_session=SimpleNamespace())  # type: ignore[arg-type]
    resolver.repository = FakeRepository(runtime_record=None, runtime_target=runtime_target)  # type: ignore[assignment]

    result = resolver.resolve(automation_id, require_prompt=False)

    assert result.automation_id == automation_id
    assert result.prompt_text == ""
    assert result.prompt_version == 0
    assert result.provider_slug == "openai"
    assert result.model_slug == "gpt-5"

