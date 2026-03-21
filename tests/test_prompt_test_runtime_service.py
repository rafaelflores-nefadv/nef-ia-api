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
