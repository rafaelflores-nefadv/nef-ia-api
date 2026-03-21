from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.repositories.prompt_tests.test_automation_repository import (
    PromptTestAutomationRecord,
    PromptTestAutomationRepository,
)


def test_find_runtime_reuses_existing_slug_even_when_not_marked_as_technical() -> None:
    repository = PromptTestAutomationRepository(session=SimpleNamespace())  # type: ignore[arg-type]
    existing = PromptTestAutomationRecord(
        id=uuid4(),
        name="Automacao Tecnica de Teste",
        slug="system-test-automation",
        provider_slug=None,
        model_slug=None,
        provider_id=None,
        model_id=None,
        is_technical_runtime=False,
        is_active=True,
        created_at=None,
        updated_at=None,
    )
    repository.get_by_id = lambda automation_id: None  # type: ignore[method-assign]
    repository.get_by_slug = lambda slug: existing if slug == "system-test-automation" else None  # type: ignore[method-assign]

    record = repository.find_runtime(
        preferred_id=None,
        slug="system-test-automation",
        name="Automacao Tecnica de Teste",
    )

    assert record == existing


def test_create_returns_existing_slug_record_after_duplicate_conflict() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.rollback_called = False

        def execute(self, stmt, params=None):  # type: ignore[no-untyped-def]
            raise Exception("duplicate key value violates unique constraint test_automations_slug_key")

        def commit(self) -> None:
            raise AssertionError("Commit nao deveria acontecer apos conflito de insert.")

        def rollback(self) -> None:
            self.rollback_called = True

    session = FakeSession()
    repository = PromptTestAutomationRepository(session=session)  # type: ignore[arg-type]
    existing = PromptTestAutomationRecord(
        id=uuid4(),
        name="Automacao Tecnica de Teste",
        slug="system-test-automation",
        provider_slug=None,
        model_slug=None,
        provider_id=None,
        model_id=None,
        is_technical_runtime=True,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repository.get_by_id = lambda automation_id: None  # type: ignore[method-assign]
    repository.get_by_slug = lambda slug: existing if slug == "system-test-automation" else None  # type: ignore[method-assign]

    record = repository.create(
        automation_id=uuid4(),
        name="Automacao Tecnica de Teste",
        slug="system-test-automation",
        provider_slug=None,
        model_slug=None,
        provider_id=None,
        model_id=None,
        is_technical_runtime=True,
        is_active=True,
    )

    assert record == existing
    assert session.rollback_called is True
