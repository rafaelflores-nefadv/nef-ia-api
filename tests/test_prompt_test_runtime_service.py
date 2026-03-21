from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.prompt_test_runtime_service import PromptTestRuntimeService


def _build_service() -> PromptTestRuntimeService:
    return PromptTestRuntimeService(shared_session=SimpleNamespace())  # type: ignore[arg-type]


def test_runtime_value_prefers_uuid_identifier_columns() -> None:
    service = _build_service()
    provider_id = uuid4()
    value = service._resolve_runtime_value_for_column(
        column_name="provider",
        column_meta={"data_type": "uuid", "udt_name": "uuid"},
        slug_value="openai",
        id_value=provider_id,
    )
    assert value == provider_id


def test_runtime_value_uses_slug_for_text_columns() -> None:
    service = _build_service()
    value = service._resolve_runtime_value_for_column(
        column_name="provider_slug",
        column_meta={"data_type": "character varying", "udt_name": "varchar"},
        slug_value="openai",
        id_value=uuid4(),
    )
    assert value == "openai"


def test_runtime_value_returns_none_for_integer_identifier_without_numeric_source() -> None:
    service = _build_service()
    value = service._resolve_runtime_value_for_column(
        column_name="provider_id",
        column_meta={"data_type": "integer", "udt_name": "int4"},
        slug_value="openai",
        id_value=uuid4(),
    )
    assert value is None


def test_guess_value_uses_prompt_test_runtime_marker() -> None:
    service = _build_service()
    value = service._guess_value_for_required_column(
        table_name="analysis_requests",
        column_name="type",
        column_meta={"data_type": "character varying", "udt_name": "varchar"},
        now=datetime.now(timezone.utc),
        automation_id=uuid4(),
        automation_name="",
        automation_slug="",
    )
    assert value == "prompt_test_runtime"


def test_create_manual_test_automation_creates_distinct_records() -> None:
    created_payloads: list[dict[str, object]] = []

    class FakeRepository:
        def ensure_schema(self) -> None:
            return None

        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            created_payloads.append(kwargs)
            return SimpleNamespace(
                id=kwargs["automation_id"],
                name=kwargs["name"],
                slug=kwargs["slug"],
                provider_slug=kwargs["provider_slug"],
                model_slug=kwargs["model_slug"],
            )

    service = _build_service()
    service.test_automations = FakeRepository()  # type: ignore[assignment]

    first = service.create_manual_test_automation(
        automation_name="Teste OCR",
        provider_slug="openai",
        model_slug="gpt-4.1-mini",
    )
    second = service.create_manual_test_automation(
        automation_name="Teste OCR",
        provider_slug="openai",
        model_slug="gpt-4.1-mini",
    )

    assert first.automation_id != second.automation_id
    assert first.automation_slug != second.automation_slug
    assert len(created_payloads) == 2
    assert all(payload["is_technical_runtime"] is False for payload in created_payloads)
