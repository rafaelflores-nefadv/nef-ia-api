from types import SimpleNamespace
from uuid import uuid4

from app.repositories.shared.automation_repository import SharedAutomationRepository


def test_build_automation_select_sql_defaults_is_active_to_true_when_missing() -> None:
    select_sql = SharedAutomationRepository._build_automation_select_sql(
        table_alias="a",
        available_columns={"id", "name"},
    )

    assert "a.name AS name" in select_sql
    assert "TRUE AS is_active" in select_sql
    assert "a.is_active" not in select_sql


def test_build_automation_record_defaults_missing_is_active_to_true() -> None:
    repository = SharedAutomationRepository(session=SimpleNamespace())  # type: ignore[arg-type]
    automation_id = uuid4()

    record = repository._build_automation_record(
        {"id": str(automation_id), "name": "Automacao tecnica"},
        available_columns={"id", "name"},
    )

    assert record is not None
    assert record.id == automation_id
    assert record.name == "Automacao tecnica"
    assert record.is_active is True


def test_build_automation_record_preserves_explicit_false_status() -> None:
    repository = SharedAutomationRepository(session=SimpleNamespace())  # type: ignore[arg-type]
    automation_id = uuid4()

    record = repository._build_automation_record(
        {"id": str(automation_id), "name": "Automacao oficial", "is_active": False},
        available_columns={"id", "name", "is_active"},
    )

    assert record is not None
    assert record.is_active is False
