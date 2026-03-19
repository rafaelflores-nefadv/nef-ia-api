import httpx
import pytest

from app.core.exceptions import AppException
from app.services.providers.anthropic_client import AnthropicAdminClient


def _response(status_code: int, *, payload: dict) -> httpx.Response:
    request = httpx.Request("GET", "https://api.anthropic.com/v1/models")
    return httpx.Response(status_code, json=payload, request=request)


def test_anthropic_list_models_success(monkeypatch) -> None:
    client = AnthropicAdminClient()

    def fake_get(url, *, headers, timeout):  # type: ignore[no-untyped-def]
        assert url.endswith("/v1/models")
        assert headers["x-api-key"] == "sk-ant-live"
        assert headers["anthropic-version"] == "2023-06-01"
        assert timeout == 15
        return _response(
            200,
            payload={
                "data": [
                    {"id": "claude-3-7-sonnet-latest", "display_name": "Claude 3.7 Sonnet"},
                ]
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    payload = client.list_models(
        api_key="sk-ant-live",
        config_json={"timeout_seconds": 15},
        anthropic_version="2023-06-01",
        default_timeout_seconds=30,
    )
    assert payload[0]["id"] == "claude-3-7-sonnet-latest"


def test_anthropic_list_models_invalid_api_key(monkeypatch) -> None:
    client = AnthropicAdminClient()

    def fake_get(url, *, headers, timeout):  # type: ignore[no-untyped-def]
        return _response(
            401,
            payload={
                "type": "error",
                "error": {
                    "type": "authentication_error",
                    "message": "invalid x-api-key",
                },
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(AppException) as exc:
        client.list_models(
            api_key="sk-ant-invalid",
            config_json={},
            anthropic_version="2023-06-01",
            default_timeout_seconds=30,
        )
    assert exc.value.payload.code == "provider_http_error"
    assert exc.value.payload.details["status_code"] == 401
    assert exc.value.payload.details["provider_error_type"] == "authentication_error"


def test_anthropic_list_models_timeout(monkeypatch) -> None:
    client = AnthropicAdminClient()

    def fake_get(url, *, headers, timeout):  # type: ignore[no-untyped-def]
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(AppException) as exc:
        client.list_models(
            api_key="sk-ant-live",
            config_json={},
            anthropic_version="2023-06-01",
            default_timeout_seconds=30,
        )
    assert exc.value.payload.code == "provider_timeout"


def test_anthropic_list_models_network_error(monkeypatch) -> None:
    client = AnthropicAdminClient()

    def fake_get(url, *, headers, timeout):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("dns error")

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(AppException) as exc:
        client.list_models(
            api_key="sk-ant-live",
            config_json={},
            anthropic_version="2023-06-01",
            default_timeout_seconds=30,
        )
    assert exc.value.payload.code == "provider_network_error"
