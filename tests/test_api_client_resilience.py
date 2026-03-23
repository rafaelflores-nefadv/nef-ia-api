import sys
import types
from collections.abc import Callable

import httpx
from django.db.utils import InterfaceError

from core.services.api_client import ApiResponse, FastAPIClient


class _BrokenQuerySet:
    def select_related(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self

    def first(self):  # type: ignore[no-untyped-def]
        raise InterfaceError("simulated transient DB interface failure")


def test_load_db_integration_config_handles_interface_error(monkeypatch) -> None:
    fake_models = types.ModuleType("core.models")
    fake_models.FastAPIIntegrationConfig = types.SimpleNamespace(objects=_BrokenQuerySet())
    fake_models.FastAPIIntegrationToken = types.SimpleNamespace(objects=_BrokenQuerySet())
    monkeypatch.setitem(sys.modules, "core.models", fake_models)

    state = {"closed_old_connections": False, "warning_logged": False}

    monkeypatch.setattr(
        "core.services.api_client.close_old_connections",
        lambda: state.__setitem__("closed_old_connections", True),  # type: ignore[no-untyped-def]
    )
    monkeypatch.setattr(
        "core.services.api_client.logger.warning",
        lambda *args, **kwargs: state.__setitem__("warning_logged", True),  # type: ignore[no-untyped-def]
    )

    client = FastAPIClient.__new__(FastAPIClient)
    payload = client._load_db_integration_config()

    assert payload is None
    assert state["closed_old_connections"] is True
    assert state["warning_logged"] is True


def test_parse_json_response_non_json_includes_status_content_type_and_preview() -> None:
    client = FastAPIClient.__new__(FastAPIClient)
    response = httpx.Response(
        status_code=502,
        headers={"content-type": "text/html"},
        content=b"<html><body>Gateway error</body></html>",
        request=httpx.Request("POST", "http://testserver/api/v1/admin/prompt-tests/executions"),
    )

    parsed = client._parse_json_response(
        response=response,
        path="/api/v1/admin/prompt-tests/executions",
        expect_dict=True,
    )

    assert parsed.status_code == 502
    assert parsed.data is None
    assert parsed.error is not None
    assert "HTTP=502" in parsed.error
    assert "content-type=text/html" in parsed.error
    assert "Gateway error" in parsed.error


def _build_client_for_http_request_tests() -> FastAPIClient:
    client = FastAPIClient.__new__(FastAPIClient)
    client.timeout = 2.5
    client.base_url = "http://127.0.0.1:8000"
    client.admin_token = ""
    client.integration_active = True
    return client


def _assert_timeout_error_message(
    monkeypatch,
    *,
    error_factory: Callable[[httpx.Request], Exception],
    expected_error: str,
) -> None:  # type: ignore[no-untyped-def]
    class _FakeClient:
        def __init__(self, *, timeout):  # type: ignore[no-untyped-def]
            self.timeout = timeout

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        def request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
            raise error_factory(httpx.Request(method, url))

    monkeypatch.setattr("core.services.api_client.httpx.Client", _FakeClient)
    client = _build_client_for_http_request_tests()
    response = client._perform_http_request(method="GET", path="/api/v1/admin/health")

    assert isinstance(response, ApiResponse)
    assert response.status_code is None
    assert response.error == expected_error


def test_perform_http_request_connect_timeout_message(monkeypatch) -> None:
    _assert_timeout_error_message(
        monkeypatch,
        error_factory=lambda request: httpx.ConnectTimeout("connect timeout", request=request),
        expected_error="Tempo limite de conexao com a FastAPI.",
    )


def test_perform_http_request_read_timeout_message(monkeypatch) -> None:
    _assert_timeout_error_message(
        monkeypatch,
        error_factory=lambda request: httpx.ReadTimeout("read timeout", request=request),
        expected_error="Tempo limite de leitura/resposta da FastAPI.",
    )
