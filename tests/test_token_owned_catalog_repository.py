from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import JSONB

from app.repositories.shared import TokenOwnedAutomationRecord, TokenOwnedCatalogRepository


class _FakeExecuteResult:
    def __init__(self, *, rowcount: int = 1) -> None:
        self.rowcount = rowcount


class _CaptureSession:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    def execute(self, stmt, params=None):  # type: ignore[no-untyped-def]
        self.calls.append((stmt, dict(params or {})))
        return _FakeExecuteResult(rowcount=1)


class _ScalarRows:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _MappingRows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def first(self) -> dict[str, object] | None:
        if not self._rows:
            return None
        return dict(self._rows[0])

    def all(self) -> list[dict[str, object]]:
        return [dict(row) for row in self._rows]


class _LookupExecuteResult:
    def __init__(
        self,
        *,
        scalars: list[object] | None = None,
        mappings: list[dict[str, object]] | None = None,
    ) -> None:
        self._scalars = list(scalars or [])
        self._mappings = list(mappings or [])

    def scalars(self) -> _ScalarRows:
        return _ScalarRows(self._scalars)

    def mappings(self) -> _MappingRows:
        return _MappingRows(self._mappings)


class _LookupSession:
    def __init__(self, *, row: dict[str, object]) -> None:
        self.row = dict(row)

    def execute(self, stmt, params=None):  # type: ignore[no-untyped-def]
        sql = str(stmt)
        if "information_schema.columns" in sql:
            return _LookupExecuteResult(
                scalars=[
                    "id",
                    "name",
                    "provider_id",
                    "model_id",
                    "credential_id",
                    "output_type",
                    "result_parser",
                    "result_formatter",
                    "output_schema",
                    "is_active",
                    "owner_token_id",
                ]
            )
        return _LookupExecuteResult(mappings=[self.row])


def _column_meta(
    *,
    data_type: str,
    udt_name: str,
    is_nullable: str = "NO",
    column_default: str | None = None,
) -> dict[str, object]:
    return {
        "is_nullable": is_nullable,
        "column_default": column_default,
        "data_type": data_type,
        "udt_name": udt_name,
    }


def _build_record(*, automation_id: UUID, token_id: UUID, output_schema: dict[str, object]) -> TokenOwnedAutomationRecord:
    return TokenOwnedAutomationRecord(
        id=automation_id,
        name="Automation",
        provider_id=uuid4(),
        model_id=uuid4(),
        credential_id=None,
        output_type="spreadsheet_output",
        result_parser="tabular_structured",
        result_formatter="spreadsheet_tabular",
        output_schema=output_schema,
        is_active=True,
        owner_token_id=token_id,
    )


def test_create_automation_binds_output_schema_as_jsonb(monkeypatch) -> None:
    session = _CaptureSession()
    repository = TokenOwnedCatalogRepository(session)
    token_id = uuid4()
    provider_id = uuid4()
    model_id = uuid4()
    output_schema = {"columns": ["numero_processo", "categoria"]}
    created_record = _build_record(automation_id=uuid4(), token_id=token_id, output_schema=output_schema)

    metadata = {
        "id": _column_meta(data_type="uuid", udt_name="uuid"),
        "name": _column_meta(data_type="character varying", udt_name="varchar"),
        "owner_token_id": _column_meta(data_type="uuid", udt_name="uuid"),
        "provider_id": _column_meta(data_type="uuid", udt_name="uuid"),
        "model_id": _column_meta(data_type="uuid", udt_name="uuid"),
        "output_schema": _column_meta(data_type="jsonb", udt_name="jsonb", is_nullable="YES"),
    }

    monkeypatch.setattr(repository, "_get_table_columns_metadata", lambda table_name: metadata)
    monkeypatch.setattr(repository, "get_automation_by_id_and_token", lambda **kwargs: created_record)

    created = repository.create_automation(
        token_id=token_id,
        name="Automation",
        provider_id=provider_id,
        model_id=model_id,
        output_schema=output_schema,
    )

    assert created == created_record
    assert len(session.calls) == 1
    stmt, params = session.calls[0]
    bind_param = stmt._bindparams.get("output_schema")  # type: ignore[attr-defined]
    assert bind_param is not None
    assert isinstance(bind_param.type, JSONB)
    assert params["output_schema"] == output_schema


def test_update_automation_binds_output_schema_as_jsonb(monkeypatch) -> None:
    session = _CaptureSession()
    repository = TokenOwnedCatalogRepository(session)
    token_id = uuid4()
    automation_id = uuid4()
    output_schema = {"file_name_template": "execution_{execution_id}.json"}
    updated_record = _build_record(automation_id=automation_id, token_id=token_id, output_schema=output_schema)

    metadata = {
        "id": _column_meta(data_type="uuid", udt_name="uuid"),
        "owner_token_id": _column_meta(data_type="uuid", udt_name="uuid"),
        "output_schema": _column_meta(data_type="jsonb", udt_name="jsonb", is_nullable="YES"),
    }

    monkeypatch.setattr(repository, "_get_table_columns_metadata", lambda table_name: metadata)
    monkeypatch.setattr(repository, "get_automation_by_id_and_token", lambda **kwargs: updated_record)

    updated = repository.update_automation(
        token_id=token_id,
        automation_id=automation_id,
        changes={"output_schema": output_schema},
    )

    assert updated == updated_record
    assert len(session.calls) == 1
    stmt, params = session.calls[0]
    bind_param = stmt._bindparams.get("output_schema")  # type: ignore[attr-defined]
    assert bind_param is not None
    assert isinstance(bind_param.type, JSONB)
    assert params["output_schema"] == output_schema


def test_get_automation_by_id_and_token_builds_record_with_is_active() -> None:
    token_id = uuid4()
    automation_id = uuid4()
    provider_id = uuid4()
    model_id = uuid4()
    session = _LookupSession(
        row={
            "id": automation_id,
            "name": "Automation",
            "provider_id": provider_id,
            "model_id": model_id,
            "credential_id": None,
            "output_type": "spreadsheet_output",
            "result_parser": "tabular_structured",
            "result_formatter": "spreadsheet_tabular",
            "output_schema": {"columns": ["numero_processo", "categoria"]},
            "is_active": "false",
            "owner_token_id": token_id,
        }
    )
    repository = TokenOwnedCatalogRepository(session)  # type: ignore[arg-type]

    item = repository.get_automation_by_id_and_token(
        automation_id=automation_id,
        token_id=token_id,
    )

    assert item is not None
    assert item.id == automation_id
    assert item.provider_id == provider_id
    assert item.model_id == model_id
    assert item.output_schema == {"columns": ["numero_processo", "categoria"]}
    assert item.is_active is False
