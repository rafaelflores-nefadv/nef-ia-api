from __future__ import annotations

from decimal import Decimal
from time import sleep
from uuid import uuid4

from app.services.prompt_test_async_execution_service import (
    PromptTestAsyncExecutionService,
    PromptTestAsyncStartPayload,
)
from app.services.prompt_test_engine_service import PromptTestEngineResult, PromptTestProgressUpdate


def test_prompt_test_async_service_exposes_real_milestones(monkeypatch) -> None:
    class FakePromptTestEngineService:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            _ = kwargs

        def execute(self, **kwargs) -> PromptTestEngineResult:  # type: ignore[no-untyped-def]
            callback = kwargs.get("progress_callback")
            if callback is not None:
                callback(
                    PromptTestProgressUpdate(
                        phase="validating_file",
                        progress_percent=15,
                        status_message="Validando arquivo.",
                    )
                )
                callback(
                    PromptTestProgressUpdate(
                        phase="running_model",
                        progress_percent=64,
                        status_message="Executando modelo.",
                        processed_rows=32,
                        total_rows=50,
                        current_row=33,
                    )
                )
            return PromptTestEngineResult(
                status="completed",
                provider_id=str(uuid4()),
                provider_slug="openai",
                model_id=str(uuid4()),
                model_slug="gpt-5",
                credential_id=None,
                credential_name="",
                prompt_override_applied=True,
                result_type="text",
                output_text="ok",
                output_file_name=None,
                output_file_mime_type="text/plain",
                output_file_base64=None,
                output_file_checksum=None,
                output_file_size=2,
                provider_calls=1,
                input_tokens=10,
                output_tokens=20,
                estimated_cost=Decimal("0.001"),
                duration_ms=120,
                processing_summary={"processed_rows": 50, "total_rows": 50},
            )

    monkeypatch.setattr(
        "app.services.prompt_test_async_execution_service.PromptTestEngineService",
        FakePromptTestEngineService,
    )

    service = PromptTestAsyncExecutionService()
    start_snapshot = service.start_execution(
        payload=PromptTestAsyncStartPayload(
            provider_id=str(uuid4()),
            model_id=str(uuid4()),
            credential_id=None,
            prompt_override="prompt",
            output_type="text_output",
            result_parser="text_raw",
            result_formatter="text_plain",
            output_schema=None,
            upload_file_name="entrada.txt",
            upload_content=b"conteudo",
            upload_content_type="text/plain",
        )
    )

    assert start_snapshot.status in {"queued", "running", "completed"}
    assert start_snapshot.progress_percent >= 0

    terminal_snapshot = None
    for _ in range(50):
        snapshot = service.get_snapshot(execution_id=start_snapshot.execution_id)
        assert snapshot is not None
        if snapshot.is_terminal:
            terminal_snapshot = snapshot
            break
        sleep(0.02)

    assert terminal_snapshot is not None
    assert terminal_snapshot.status == "completed"
    assert terminal_snapshot.phase == "completed"
    assert terminal_snapshot.progress_percent == 100
    assert terminal_snapshot.result_ready is True
    assert terminal_snapshot.total_rows == 50
    assert terminal_snapshot.current_row == 50


def test_prompt_test_async_service_failed_status_keeps_real_progress(monkeypatch) -> None:
    class FakePromptTestEngineService:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            _ = kwargs

        def execute(self, **kwargs):  # type: ignore[no-untyped-def]
            callback = kwargs.get("progress_callback")
            if callback is not None:
                callback(
                    PromptTestProgressUpdate(
                        phase="processing_rows",
                        progress_percent=41,
                        status_message="Processando linhas.",
                        processed_rows=8,
                        total_rows=20,
                        current_row=9,
                    )
                )
            raise RuntimeError("falha simulada")

    monkeypatch.setattr(
        "app.services.prompt_test_async_execution_service.PromptTestEngineService",
        FakePromptTestEngineService,
    )

    service = PromptTestAsyncExecutionService()
    start_snapshot = service.start_execution(
        payload=PromptTestAsyncStartPayload(
            provider_id=str(uuid4()),
            model_id=str(uuid4()),
            credential_id=None,
            prompt_override="prompt",
            output_type="text_output",
            result_parser="text_raw",
            result_formatter="text_plain",
            output_schema=None,
            upload_file_name="entrada.txt",
            upload_content=b"conteudo",
            upload_content_type="text/plain",
        )
    )

    terminal_snapshot = None
    for _ in range(50):
        snapshot = service.get_snapshot(execution_id=start_snapshot.execution_id)
        assert snapshot is not None
        if snapshot.is_terminal:
            terminal_snapshot = snapshot
            break
        sleep(0.02)

    assert terminal_snapshot is not None
    assert terminal_snapshot.status == "failed"
    assert terminal_snapshot.progress_percent >= 41
    assert terminal_snapshot.progress_percent < 100
    assert terminal_snapshot.total_rows == 20
    assert terminal_snapshot.current_row == 9
