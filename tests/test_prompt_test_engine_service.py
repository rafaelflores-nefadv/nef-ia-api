import io
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

import app.services.prompt_test_engine_service as prompt_test_module
from app.core.exceptions import AppException
from app.integrations.storage.local import LocalStorageProvider
from app.services.execution_engine import ExecutionFileKind
from app.services.prompt_test_engine_service import PromptTestEngineService


def _build_upload(*, file_name: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        filename=file_name,
        file=io.BytesIO(content),
        headers=Headers({"content-type": content_type}),
    )


class FakeExecutionService:
    def __init__(
        self,
        *,
        storage_root: Path,
        output_file_name: str = "resultado.xlsx",
        output_content: bytes = b"conteudo-binario-planilha",
        output_mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        raise_on_process: bool = False,
        max_size_bytes: int = 5 * 1024 * 1024,
    ) -> None:
        self.storage = LocalStorageProvider(root_path=storage_root)
        self.file_service = SimpleNamespace(
            _validate_upload_file=lambda upload_file: None,
            storage=self.storage,
            max_size_bytes=max_size_bytes,
            allowed_mimes={"text/plain", "text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        )
        self.provider_service = SimpleNamespace(
            _coerce_uuid=self._coerce_uuid,
            resolve_runtime=self._resolve_runtime,
        )
        self.strategy_engine = SimpleNamespace(detect_file_kind=self._detect_file_kind)
        self.usage_service = SimpleNamespace(register_usage=lambda **_: None)
        self.output_file_name = output_file_name
        self.output_content = output_content
        self.output_mime_type = output_mime_type
        self.raise_on_process = raise_on_process
        self.saved_relative_path: str | None = None
        self.saved_file_kind: ExecutionFileKind | None = None
        self.read_payload: bytes | None = None
        self.last_debug_enabled: bool = False

    @staticmethod
    def _coerce_uuid(value: str | None) -> UUID | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        return UUID(normalized)

    @staticmethod
    def _resolve_runtime(*, provider_slug: str, model_slug: str, credential_id: UUID | None) -> SimpleNamespace:
        return SimpleNamespace(
            provider=SimpleNamespace(id=uuid4(), slug=provider_slug),
            model=SimpleNamespace(id=uuid4(), model_slug=model_slug),
            credential=SimpleNamespace(id=credential_id or uuid4(), credential_name="Credencial teste"),
        )

    @staticmethod
    def _detect_file_kind(*, file_name: str, mime_type: str | None) -> ExecutionFileKind:
        extension = Path(file_name).suffix.lower()
        if extension in {".csv", ".xlsx"}:
            return ExecutionFileKind.TABULAR
        if extension in {".txt", ".md", ".pdf"}:
            return ExecutionFileKind.TEXTUAL
        return ExecutionFileKind.UNSUPPORTED

    @staticmethod
    def build_direct_execution_profile() -> SimpleNamespace:
        return SimpleNamespace(name="direct_prompt_test")

    def _resolve_execution_output_contract(  # type: ignore[no-untyped-def]
        self,
        *,
        automation_id=None,
        automation_slug=None,
        processing_plan=None,
        runtime_output_type=None,
        runtime_result_parser=None,
        runtime_result_formatter=None,
        runtime_output_schema=None,
    ):
        if processing_plan is not None:
            return SimpleNamespace(
                output_type=getattr(processing_plan, "output_type", "spreadsheet_output"),
                parser_strategy=getattr(processing_plan, "parser_strategy", "tabular_structured"),
                formatter_strategy="spreadsheet_tabular",
                output_schema={},
            )
        return SimpleNamespace(
            output_type="spreadsheet_output",
            parser_strategy="tabular_structured",
            formatter_strategy="spreadsheet_tabular",
            output_schema={},
        )

    def _resolve_processing_strategy(  # type: ignore[no-untyped-def]
        self,
        *,
        processing_inputs: list,
        output_contract=None,
    ) -> SimpleNamespace:
        primary = processing_inputs[0]
        self.saved_relative_path = primary.file_path
        self.saved_file_kind = primary.file_kind
        parser_strategy = "tabular_structured"
        output_type = "spreadsheet_output"
        if output_contract is not None:
            parser_strategy = str(getattr(output_contract, "parser_strategy", parser_strategy))
            output_type = str(getattr(output_contract, "output_type", output_type))
        return SimpleNamespace(
            primary_input=primary,
            input_type="tabular",
            context_inputs=[],
            ordered_inputs=[primary],
            parser_strategy=parser_strategy,
            output_type=output_type,
        )

    def _process_execution_by_strategy(self, **kwargs):  # type: ignore[no-untyped-def]
        processing_plan = kwargs["processing_plan"]
        self.last_debug_enabled = bool(kwargs.get("debug_enabled", False))
        progress_callback = kwargs.get("progress_callback")
        relative_path = str(processing_plan.primary_input.file_path)
        assert not Path(relative_path).is_absolute()
        with self.storage.open_file(relative_path) as handle:
            self.read_payload = handle.read()
        if progress_callback is not None:
            progress_callback(
                SimpleNamespace(
                    phase="processing_rows",
                    status_message="Processamento iniciado.",
                    processed_rows=0,
                    total_rows=4,
                    current_row=None,
                    processed_chunks=None,
                    total_chunks=None,
                )
            )
            progress_callback(
                SimpleNamespace(
                    phase="processing_rows",
                    status_message="Linha processada.",
                    processed_rows=2,
                    total_rows=4,
                    current_row=2,
                    processed_chunks=None,
                    total_chunks=None,
                )
            )
            progress_callback(
                SimpleNamespace(
                    phase="processing_rows",
                    status_message="Processamento finalizado.",
                    processed_rows=4,
                    total_rows=4,
                    current_row=4,
                    processed_chunks=None,
                    total_chunks=None,
                )
            )
            progress_callback(
                SimpleNamespace(
                    phase="normalizing_output",
                    status_message="Normalizando saida.",
                    processed_rows=4,
                    total_rows=4,
                    current_row=4,
                    processed_chunks=None,
                    total_chunks=None,
                )
            )
            progress_callback(
                SimpleNamespace(
                    phase="exporting_result",
                    status_message="Exportando resultado.",
                    processed_rows=4,
                    total_rows=4,
                    current_row=4,
                    processed_chunks=None,
                    total_chunks=None,
                )
            )
        if self.raise_on_process:
            raise AppException("Falha simulada de processamento.", status_code=500, code="processing_failed")
        auxiliary_files = []
        if self.last_debug_enabled:
            auxiliary_files = [
                SimpleNamespace(
                    file_type="debug",
                    file_name="debug_execucao.xlsx",
                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    content=b"debug-content",
                )
            ]
        return SimpleNamespace(
            content=self.output_content,
            file_name=self.output_file_name,
            mime_type=self.output_mime_type,
            provider_calls=1,
            total_input_tokens=10,
            total_output_tokens=20,
            total_cost=Decimal("0.001"),
            processing_summary={"input_type": "tabular"},
            auxiliary_files=auxiliary_files,
        )


@pytest.mark.parametrize(
    ("file_name", "content_type"),
    [
        ("entrada.csv", "text/csv"),
        ("entrada.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ],
)
def test_prompt_test_upload_uses_storage_relative_path_and_cleans_file(
    monkeypatch,
    tmp_path,
    file_name: str,
    content_type: str,
) -> None:
    fake_execution_service = FakeExecutionService(storage_root=tmp_path)
    monkeypatch.setattr(
        prompt_test_module,
        "ExecutionService",
        lambda **_: fake_execution_service,
    )

    service = PromptTestEngineService(
        operational_session=SimpleNamespace(),
        shared_session=SimpleNamespace(),
    )
    payload = b"coluna\nvalor\n"
    result = service.execute(
        provider_id=str(uuid4()),
        model_id=str(uuid4()),
        credential_id=str(uuid4()),
        prompt_override="Prompt de teste",
        upload_file=_build_upload(file_name=file_name, content=payload, content_type=content_type),
    )

    assert result.status == "completed"
    assert result.result_type == "file"
    assert fake_execution_service.saved_relative_path is not None
    assert not Path(fake_execution_service.saved_relative_path).is_absolute()
    assert fake_execution_service.saved_file_kind == ExecutionFileKind.TABULAR
    assert fake_execution_service.read_payload == payload

    saved_absolute_path = (fake_execution_service.storage.root_path / fake_execution_service.saved_relative_path).resolve()
    assert fake_execution_service.storage.root_path in saved_absolute_path.parents
    assert not saved_absolute_path.exists()


def test_prompt_test_upload_with_consumed_stream_still_reads_from_start(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    fake_execution_service = FakeExecutionService(storage_root=tmp_path)
    monkeypatch.setattr(
        prompt_test_module,
        "ExecutionService",
        lambda **_: fake_execution_service,
    )
    upload = _build_upload(
        file_name="entrada.csv",
        content=b"coluna\nvalor\n",
        content_type="text/csv",
    )
    _ = upload.file.read()

    service = PromptTestEngineService(
        operational_session=SimpleNamespace(),
        shared_session=SimpleNamespace(),
    )
    result = service.execute(
        provider_id=str(uuid4()),
        model_id=str(uuid4()),
        credential_id=str(uuid4()),
        prompt_override="Prompt de teste",
        upload_file=upload,
    )

    assert result.status == "completed"
    assert fake_execution_service.read_payload == b"coluna\nvalor\n"


def test_prompt_test_upload_is_deleted_on_processing_failure(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    fake_execution_service = FakeExecutionService(
        storage_root=tmp_path,
        raise_on_process=True,
    )
    monkeypatch.setattr(
        prompt_test_module,
        "ExecutionService",
        lambda **_: fake_execution_service,
    )

    service = PromptTestEngineService(
        operational_session=SimpleNamespace(),
        shared_session=SimpleNamespace(),
    )

    with pytest.raises(AppException) as exc_info:
        service.execute(
            provider_id=str(uuid4()),
            model_id=str(uuid4()),
            credential_id=None,
            prompt_override="Prompt de teste",
            upload_file=_build_upload(
                file_name="entrada.csv",
                content=b"coluna\nvalor\n",
                content_type="text/csv",
            ),
        )

    assert exc_info.value.payload.code == "processing_failed"
    assert fake_execution_service.saved_relative_path is not None
    saved_absolute_path = (fake_execution_service.storage.root_path / fake_execution_service.saved_relative_path).resolve()
    assert not saved_absolute_path.exists()


def test_prompt_test_upload_empty_file_raises_and_cleans_storage(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    fake_execution_service = FakeExecutionService(storage_root=tmp_path)
    monkeypatch.setattr(
        prompt_test_module,
        "ExecutionService",
        lambda **_: fake_execution_service,
    )

    service = PromptTestEngineService(
        operational_session=SimpleNamespace(),
        shared_session=SimpleNamespace(),
    )

    with pytest.raises(AppException) as exc_info:
        service.execute(
            provider_id=str(uuid4()),
            model_id=str(uuid4()),
            credential_id=None,
            prompt_override="Prompt de teste",
            upload_file=_build_upload(
                file_name="entrada.csv",
                content=b"",
                content_type="text/csv",
            ),
        )

    assert exc_info.value.payload.code == "empty_uploaded_file"
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


def test_prompt_test_upload_too_large_raises_file_too_large(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    fake_execution_service = FakeExecutionService(storage_root=tmp_path, max_size_bytes=4)
    monkeypatch.setattr(
        prompt_test_module,
        "ExecutionService",
        lambda **_: fake_execution_service,
    )

    service = PromptTestEngineService(
        operational_session=SimpleNamespace(),
        shared_session=SimpleNamespace(),
    )

    with pytest.raises(AppException) as exc_info:
        service.execute(
            provider_id=str(uuid4()),
            model_id=str(uuid4()),
            credential_id=None,
            prompt_override="Prompt de teste",
            upload_file=_build_upload(
                file_name="entrada.csv",
                content=b"12345",
                content_type="text/csv",
            ),
        )

    assert exc_info.value.payload.code == "file_too_large"


def test_prompt_test_textual_input_preserves_file_kind_and_text_result(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    fake_execution_service = FakeExecutionService(
        storage_root=tmp_path,
        output_file_name="resultado.txt",
        output_content=b"texto de saida",
        output_mime_type="text/plain",
    )
    monkeypatch.setattr(
        prompt_test_module,
        "ExecutionService",
        lambda **_: fake_execution_service,
    )

    service = PromptTestEngineService(
        operational_session=SimpleNamespace(),
        shared_session=SimpleNamespace(),
    )
    result = service.execute(
        provider_id=str(uuid4()),
        model_id=str(uuid4()),
        credential_id=None,
        prompt_override="Prompt de teste",
        upload_file=_build_upload(
            file_name="entrada.txt",
            content=b"conteudo texto",
            content_type="text/plain",
        ),
    )

    assert fake_execution_service.saved_file_kind == ExecutionFileKind.TEXTUAL
    assert result.result_type == "text"
    assert result.output_text == "texto de saida"


def test_prompt_test_missing_filename_raises(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    fake_execution_service = FakeExecutionService(storage_root=tmp_path)
    monkeypatch.setattr(
        prompt_test_module,
        "ExecutionService",
        lambda **_: fake_execution_service,
    )

    service = PromptTestEngineService(
        operational_session=SimpleNamespace(),
        shared_session=SimpleNamespace(),
    )

    with pytest.raises(AppException) as exc_info:
        service.execute(
            provider_id=str(uuid4()),
            model_id=str(uuid4()),
            credential_id=None,
            prompt_override="Prompt de teste",
            upload_file=_build_upload(
                file_name="",
                content=b"conteudo",
                content_type="text/plain",
            ),
        )

    assert exc_info.value.payload.code == "missing_file_name"


def test_prompt_test_propagates_base_invalid_extension_validation(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    fake_execution_service = FakeExecutionService(storage_root=tmp_path)

    def _raise_invalid_extension(upload_file: UploadFile) -> None:
        raise AppException(
            "Unsupported file extension.",
            status_code=400,
            code="invalid_file_extension",
            details={"allowed_extensions": [".csv", ".xlsx", ".pdf"]},
        )

    fake_execution_service.file_service._validate_upload_file = _raise_invalid_extension
    monkeypatch.setattr(
        prompt_test_module,
        "ExecutionService",
        lambda **_: fake_execution_service,
    )

    service = PromptTestEngineService(
        operational_session=SimpleNamespace(),
        shared_session=SimpleNamespace(),
    )

    with pytest.raises(AppException) as exc_info:
        service.execute(
            provider_id=str(uuid4()),
            model_id=str(uuid4()),
            credential_id=None,
            prompt_override="Prompt de teste",
            upload_file=_build_upload(
                file_name="entrada.txt",
                content=b"conteudo texto",
                content_type="text/plain",
            ),
        )

    assert exc_info.value.payload.code == "invalid_file_extension"


def test_prompt_test_emits_real_progress_milestones(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    fake_execution_service = FakeExecutionService(storage_root=tmp_path)
    monkeypatch.setattr(
        prompt_test_module,
        "ExecutionService",
        lambda **_: fake_execution_service,
    )

    service = PromptTestEngineService(
        operational_session=SimpleNamespace(),
        shared_session=SimpleNamespace(),
    )
    updates: list[tuple[str, int, int | None, int | None, int | None]] = []

    result = service.execute(
        provider_id=str(uuid4()),
        model_id=str(uuid4()),
        credential_id=None,
        prompt_override="Prompt de teste",
        upload_file=_build_upload(
            file_name="entrada.csv",
            content=b"coluna\nvalor\n",
            content_type="text/csv",
        ),
        progress_callback=lambda update: updates.append(
            (
                update.phase,
                update.progress_percent,
                update.processed_rows,
                update.total_rows,
                update.current_row,
            )
        ),
    )

    assert result.status == "completed"
    phases = [phase for phase, *_ in updates]
    percents = [percent for _, percent, *_ in updates]
    assert "preparing_input" in phases
    assert "validating_file" in phases
    assert "processing_rows" in phases
    assert "normalizing_output" in phases
    assert "exporting_result" in phases
    assert percents == sorted(percents)
    row_updates = [item for item in updates if item[0] == "processing_rows" and item[2] is not None]
    assert row_updates
    assert row_updates[-1][2] == 4
    assert row_updates[-1][3] == 4
    assert row_updates[-1][4] == 4


def test_prompt_test_debug_disabled_returns_only_primary_output(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    fake_execution_service = FakeExecutionService(storage_root=tmp_path)
    monkeypatch.setattr(
        prompt_test_module,
        "ExecutionService",
        lambda **_: fake_execution_service,
    )

    service = PromptTestEngineService(
        operational_session=SimpleNamespace(),
        shared_session=SimpleNamespace(),
    )
    result = service.execute(
        provider_id=str(uuid4()),
        model_id=str(uuid4()),
        credential_id=None,
        prompt_override="Prompt de teste",
        upload_file=_build_upload(
            file_name="entrada.csv",
            content=b"coluna\nvalor\n",
            content_type="text/csv",
        ),
        debug_enabled=False,
    )

    assert fake_execution_service.last_debug_enabled is False
    assert result.output_file_base64 is not None
    assert result.debug_file_name is None
    assert result.debug_file_base64 is None
    assert result.debug_file_size == 0


def test_prompt_test_debug_enabled_returns_debug_file(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    fake_execution_service = FakeExecutionService(storage_root=tmp_path)
    monkeypatch.setattr(
        prompt_test_module,
        "ExecutionService",
        lambda **_: fake_execution_service,
    )

    service = PromptTestEngineService(
        operational_session=SimpleNamespace(),
        shared_session=SimpleNamespace(),
    )
    result = service.execute(
        provider_id=str(uuid4()),
        model_id=str(uuid4()),
        credential_id=None,
        prompt_override="Prompt de teste",
        upload_file=_build_upload(
            file_name="entrada.csv",
            content=b"coluna\nvalor\n",
            content_type="text/csv",
        ),
        debug_enabled=True,
    )

    assert fake_execution_service.last_debug_enabled is True
    assert result.output_file_base64 is not None
    assert result.debug_file_name == "debug_execucao.xlsx"
    assert result.debug_file_mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert result.debug_file_base64 is not None
    assert result.debug_file_checksum is not None
    assert result.debug_file_size > 0
