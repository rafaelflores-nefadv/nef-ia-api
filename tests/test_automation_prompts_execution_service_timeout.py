from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from core.services.api_client import ApiResponse
from core.services.automation_prompts_execution_service import AutomationPromptsExecutionService


class _FakeClient:
    def __init__(self) -> None:
        self.last_timeout = None
        self.last_data = None

    def get_admin_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer test"}

    def request_multipart(self, **kwargs):  # type: ignore[no-untyped-def]
        self.last_timeout = kwargs.get("timeout")
        self.last_data = kwargs.get("data")
        provider_id = kwargs["data"]["provider_id"]
        model_id = kwargs["data"]["model_id"]
        return ApiResponse(
            status_code=200,
            data={
                "status": "completed",
                "provider_id": provider_id,
                "provider_slug": "openai",
                "model_id": model_id,
                "model_slug": "gpt-5",
                "credential_id": None,
                "credential_name": "",
                "prompt_override_applied": True,
                "result_type": "text",
                "output_text": "ok",
                "output_file_name": None,
                "output_file_mime_type": None,
                "output_file_base64": None,
                "output_file_checksum": None,
                "output_file_size": 0,
                "debug_file_name": "debug_execucao.xlsx",
                "debug_file_mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "debug_file_base64": "ZGVidWc=",
                "debug_file_checksum": "abc",
                "debug_file_size": 5,
                "provider_calls": 1,
                "input_tokens": 1,
                "output_tokens": 1,
                "estimated_cost": "0",
                "duration_ms": 1,
                "processing_summary": {},
            },
            error=None,
        )


class _FakeAsyncClient:
    def __init__(self) -> None:
        self.last_timeout = None
        self.last_data = None

    def get_admin_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer test"}

    def request_multipart(self, **kwargs):  # type: ignore[no-untyped-def]
        self.last_timeout = kwargs.get("timeout")
        self.last_data = kwargs.get("data")
        return ApiResponse(
            status_code=200,
            data={
                "execution_id": str(uuid4()),
                "status": "queued",
                "phase": "queued",
                "progress_percent": 2,
                "status_message": "Execucao enfileirada.",
                "is_terminal": False,
                "created_at": "2026-03-21T10:00:00Z",
            },
            error=None,
        )

    def get(self, path, **kwargs):  # type: ignore[no-untyped-def]
        if str(path).endswith("/status"):
            return ApiResponse(
                status_code=200,
                data={
                    "execution_id": str(uuid4()),
                    "status": "running",
                    "phase": "running_model",
                    "progress_percent": 47,
                    "status_message": "Executando modelo.",
                    "is_terminal": False,
                    "error_message": "",
                    "result_ready": False,
                    "result_type": None,
                    "output_file_name": None,
                    "output_file_mime_type": None,
                    "output_file_size": 0,
                    "debug_file_name": "debug_execucao.xlsx",
                    "debug_file_mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "debug_file_size": 1024,
                    "processed_rows": 120,
                    "total_rows": 300,
                    "current_row": 121,
                    "result_url": None,
                    "download_url": None,
                    "debug_download_url": "/debug/download",
                    "created_at": "2026-03-21T10:00:00Z",
                    "started_at": "2026-03-21T10:00:01Z",
                    "finished_at": None,
                    "updated_at": "2026-03-21T10:00:03Z",
                },
                error=None,
            )
        return ApiResponse(
            status_code=200,
            data={
                "status": "completed",
                "provider_id": str(uuid4()),
                "provider_slug": "openai",
                "model_id": str(uuid4()),
                "model_slug": "gpt-5",
                "credential_id": None,
                "credential_name": "",
                "prompt_override_applied": True,
                "result_type": "text",
                "output_text": "ok",
                "output_file_name": None,
                "output_file_mime_type": None,
                "output_file_base64": None,
                "output_file_checksum": None,
                "output_file_size": 0,
                "provider_calls": 1,
                "input_tokens": 1,
                "output_tokens": 1,
                "estimated_cost": "0",
                "duration_ms": 1,
                "processing_summary": {},
            },
            error=None,
        )


def test_execute_test_prompt_uses_extended_timeout_override(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.services.automation_prompts_execution_service.settings",
        SimpleNamespace(
            FASTAPI_TIMEOUT_SECONDS=2.5,
            FASTAPI_PROMPT_TEST_CONNECT_TIMEOUT_SECONDS=5.0,
            FASTAPI_PROMPT_TEST_READ_TIMEOUT_SECONDS=240.0,
            FASTAPI_PROMPT_TEST_WRITE_TIMEOUT_SECONDS=60.0,
            FASTAPI_PROMPT_TEST_POOL_TIMEOUT_SECONDS=30.0,
        ),
    )

    client = _FakeClient()
    service = AutomationPromptsExecutionService(client=client)  # type: ignore[arg-type]
    uploaded_file = SimpleNamespace(
        name="entrada.csv",
        content_type="text/csv",
        read=lambda: b"col1,col2\n1,2\n",
    )

    result = service.execute_test_prompt(
        provider_id=uuid4(),
        model_id=uuid4(),
        credential_id=None,
        uploaded_file=uploaded_file,
        prompt_override="prompt",
    )

    assert result.status == "completed"
    assert isinstance(client.last_timeout, httpx.Timeout)
    assert client.last_timeout.connect == pytest.approx(5.0)
    assert client.last_timeout.read == pytest.approx(240.0)
    assert client.last_timeout.write == pytest.approx(60.0)
    assert client.last_timeout.pool == pytest.approx(30.0)
    assert result.debug_file_name == "debug_execucao.xlsx"
    assert result.debug_file_size == 5


def test_execute_test_prompt_sends_debug_flag_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.services.automation_prompts_execution_service.settings",
        SimpleNamespace(
            FASTAPI_TIMEOUT_SECONDS=2.5,
            FASTAPI_PROMPT_TEST_CONNECT_TIMEOUT_SECONDS=5.0,
            FASTAPI_PROMPT_TEST_READ_TIMEOUT_SECONDS=240.0,
            FASTAPI_PROMPT_TEST_WRITE_TIMEOUT_SECONDS=60.0,
            FASTAPI_PROMPT_TEST_POOL_TIMEOUT_SECONDS=30.0,
        ),
    )
    client = _FakeClient()
    service = AutomationPromptsExecutionService(client=client)  # type: ignore[arg-type]
    uploaded_file = SimpleNamespace(
        name="entrada.csv",
        content_type="text/csv",
        read=lambda: b"col1,col2\n1,2\n",
    )

    _ = service.execute_test_prompt(
        provider_id=uuid4(),
        model_id=uuid4(),
        credential_id=None,
        uploaded_file=uploaded_file,
        prompt_override="prompt",
        debug_enabled=True,
    )

    assert isinstance(client.last_data, dict)
    assert client.last_data.get("debug_enabled") == "true"


def test_start_test_prompt_execution_returns_remote_execution_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.services.automation_prompts_execution_service.settings",
        SimpleNamespace(
            FASTAPI_TIMEOUT_SECONDS=2.5,
            FASTAPI_PROMPT_TEST_CONNECT_TIMEOUT_SECONDS=5.0,
            FASTAPI_PROMPT_TEST_READ_TIMEOUT_SECONDS=240.0,
            FASTAPI_PROMPT_TEST_WRITE_TIMEOUT_SECONDS=60.0,
            FASTAPI_PROMPT_TEST_POOL_TIMEOUT_SECONDS=30.0,
        ),
    )
    client = _FakeAsyncClient()
    service = AutomationPromptsExecutionService(client=client)  # type: ignore[arg-type]
    uploaded_file = SimpleNamespace(
        name="entrada.csv",
        content_type="text/csv",
        read=lambda: b"col1,col2\n1,2\n",
    )

    result = service.start_test_prompt_execution(
        provider_id=uuid4(),
        model_id=uuid4(),
        credential_id=None,
        uploaded_file=uploaded_file,
        prompt_override="prompt",
    )

    assert result.status == "queued"
    assert result.phase == "queued"
    assert result.progress_percent == 2
    assert isinstance(client.last_timeout, httpx.Timeout)


def test_start_test_prompt_execution_sends_debug_flag_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.services.automation_prompts_execution_service.settings",
        SimpleNamespace(
            FASTAPI_TIMEOUT_SECONDS=2.5,
            FASTAPI_PROMPT_TEST_CONNECT_TIMEOUT_SECONDS=5.0,
            FASTAPI_PROMPT_TEST_READ_TIMEOUT_SECONDS=240.0,
            FASTAPI_PROMPT_TEST_WRITE_TIMEOUT_SECONDS=60.0,
            FASTAPI_PROMPT_TEST_POOL_TIMEOUT_SECONDS=30.0,
        ),
    )
    client = _FakeAsyncClient()
    service = AutomationPromptsExecutionService(client=client)  # type: ignore[arg-type]
    uploaded_file = SimpleNamespace(
        name="entrada.csv",
        content_type="text/csv",
        read=lambda: b"col1,col2\n1,2\n",
    )

    _ = service.start_test_prompt_execution(
        provider_id=uuid4(),
        model_id=uuid4(),
        credential_id=None,
        uploaded_file=uploaded_file,
        prompt_override="prompt",
        debug_enabled=True,
    )

    assert isinstance(client.last_data, dict)
    assert client.last_data.get("debug_enabled") == "true"


def test_get_test_prompt_execution_status_returns_rich_progress_payload() -> None:
    client = _FakeAsyncClient()
    service = AutomationPromptsExecutionService(client=client)  # type: ignore[arg-type]

    payload = service.get_test_prompt_execution_status(execution_id=uuid4())

    assert payload.status == "running"
    assert payload.phase == "running_model"
    assert payload.progress_percent == 47
    assert payload.processed_rows == 120
    assert payload.total_rows == 300
    assert payload.current_row == 121
    assert payload.debug_file_name == "debug_execucao.xlsx"
    assert payload.debug_file_size == 1024
    assert payload.debug_download_url == "/debug/download"


class _FakeTokenAndCopyClient:
    def __init__(self) -> None:
        self.last_post_path = ""
        self.last_post_body = None

    def get_admin_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer test"}

    def get(self, path, **kwargs):  # type: ignore[no-untyped-def]
        assert path == "/api/v1/admin/tokens"
        return ApiResponse(
            status_code=200,
            data=[
                {"id": str(uuid4()), "name": "Destino inativo", "is_active": False},
                {"id": str(uuid4()), "name": "Destino ativo A", "is_active": True},
                {"id": str(uuid4()), "name": "Destino ativo B", "is_active": True},
            ],
            error=None,
        )

    def post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        self.last_post_path = str(path)
        self.last_post_body = kwargs.get("json_body")
        payload = dict(self.last_post_body or {})
        return ApiResponse(
            status_code=201,
            data={
                "owner_token_id": payload.get("owner_token_id"),
                "automation_id": str(uuid4()),
                "automation_name": str(payload.get("name") or ""),
                "prompt_id": str(uuid4()),
                "prompt_version": 1,
                "source_test_automation_id": payload.get("source_test_automation_id"),
                "source_test_prompt_id": payload.get("source_test_prompt_id"),
            },
            error=None,
        )


def test_list_official_owner_tokens_returns_only_active_tokens() -> None:
    client = _FakeTokenAndCopyClient()
    service = AutomationPromptsExecutionService(client=client)  # type: ignore[arg-type]

    items = service.list_official_owner_tokens()

    assert len(items) == 2
    assert all(item.is_active for item in items)
    assert sorted(item.name for item in items) == ["Destino ativo A", "Destino ativo B"]


def test_copy_test_automation_to_official_calls_admin_endpoint() -> None:
    client = _FakeTokenAndCopyClient()
    service = AutomationPromptsExecutionService(client=client)  # type: ignore[arg-type]
    owner_token_id = uuid4()
    provider_id = uuid4()
    model_id = uuid4()
    source_test_automation_id = uuid4()

    result = service.copy_test_automation_to_official(
        owner_token_id=owner_token_id,
        name="Automacao de teste",
        provider_id=provider_id,
        model_id=model_id,
        credential_id=None,
        output_type="spreadsheet_output",
        result_parser="tabular_structured",
        result_formatter="spreadsheet_tabular",
        output_schema={"columns": ["a", "b"]},
        is_active=True,
        prompt_text="PROMPT TESTE",
        source_test_automation_id=source_test_automation_id,
        source_test_prompt_id=10,
    )

    assert client.last_post_path == "/api/v1/admin/prompt-tests/automations/copy-to-official"
    assert isinstance(client.last_post_body, dict)
    assert client.last_post_body["owner_token_id"] == str(owner_token_id)
    assert client.last_post_body["provider_id"] == str(provider_id)
    assert client.last_post_body["model_id"] == str(model_id)
    assert "debug_enabled" not in client.last_post_body
    assert result.owner_token_id == owner_token_id
    assert result.automation_name == "Automacao de teste"
    assert result.source_test_automation_id == source_test_automation_id
    assert result.source_test_prompt_id == 10
