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


def test_guess_required_automation_value_uses_slug_and_name_defaults() -> None:
    automation_id = uuid4()

    slug_value = SharedAutomationRepository._guess_required_automation_value(
        column_name="slug",
        column_meta={"data_type": "character varying", "udt_name": "varchar"},
        automation_id=automation_id,
        name="Automacao Tecnica de Teste",
        slug="system-test-automation",
        now=SimpleNamespace(),  # type: ignore[arg-type]
    )
    name_value = SharedAutomationRepository._guess_required_automation_value(
        column_name="name",
        column_meta={"data_type": "character varying", "udt_name": "varchar"},
        automation_id=automation_id,
        name="Automacao Tecnica de Teste",
        slug="system-test-automation",
        now=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert slug_value == "system-test-automation"
    assert name_value == "Automacao Tecnica de Teste"


def test_ensure_technical_automation_reuses_created_row_after_create_conflict() -> None:
    automation_id = uuid4()

    class FakeRepository(SharedAutomationRepository):
        def __init__(self) -> None:
            super().__init__(session=SimpleNamespace())  # type: ignore[arg-type]
            self.create_calls = 0

        def _get_table_columns_metadata(self, table_name: str):  # type: ignore[override]
            return {
                "id": {"is_nullable": "NO", "column_default": None, "data_type": "uuid", "udt_name": "uuid"},
                "name": {"is_nullable": "NO", "column_default": None, "data_type": "character varying", "udt_name": "varchar"},
                "slug": {"is_nullable": "NO", "column_default": None, "data_type": "character varying", "udt_name": "varchar"},
            }

        def get_automation_by_id(self, automation_id_value):  # type: ignore[override]
            return None

        def find_automation_by_slug_or_name(self, *, slug, name):  # type: ignore[override]
            if self.create_calls <= 0:
                return None
            return SimpleNamespace(id=automation_id, name=name, is_active=True)

        def _create_technical_automation(self, *, automation_id, slug, name, metadata):  # type: ignore[override]
            self.create_calls += 1
            raise Exception("should not escape")  # pragma: no cover

        def _normalize_technical_automation(self, *, automation_id, slug, name, metadata):  # type: ignore[override]
            return SimpleNamespace(id=automation_id, name=name, is_active=True)

    repository = FakeRepository()

    def fake_create(**kwargs):  # type: ignore[no-untyped-def]
        repository.create_calls += 1
        from app.core.exceptions import AppException

        raise AppException(
            "conflict",
            status_code=500,
            code="test_prompt_runtime_shared_automation_create_failed",
        )

    repository._create_technical_automation = fake_create  # type: ignore[method-assign]

    record = repository.ensure_technical_automation(
        preferred_id=automation_id,
        slug="system-test-automation",
        name="Automacao Tecnica de Teste",
    )

    assert record.id == automation_id
