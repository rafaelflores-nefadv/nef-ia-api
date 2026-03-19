import httpx
import pytest

from app.core.exceptions import AppException
from app.services.providers.gemini_client import GeminiClient


def _response(method: str, url: str, status_code: int, *, payload: dict) -> httpx.Response:
    request = httpx.Request(method, url)
    return httpx.Response(status_code, json=payload, request=request)


def test_gemini_list_models_success(monkeypatch) -> None:
    client = GeminiClient()

    def fake_request(method, url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        assert method == "GET"
        assert url == "https://generativelanguage.googleapis.com/v1beta/models"
        assert headers["x-goog-api-key"] == "gemini-live-key"
        assert timeout == 10
        assert json is None
        return _response(
            "GET",
            url,
            200,
            payload={"models": [{"name": "models/gemini-2.5-pro", "displayName": "Gemini 2.5 Pro"}]},
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    payload = client.list_models(
        api_key="gemini-live-key",
        config_json={"timeout_seconds": 10},
        default_timeout_seconds=30,
    )
    assert payload[0]["name"] == "models/gemini-2.5-pro"


def test_gemini_list_models_invalid_api_key(monkeypatch) -> None:
    client = GeminiClient()

    def fake_request(method, url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        return _response(
            "GET",
            url,
            401,
            payload={
                "error": {
                    "code": 401,
                    "status": "UNAUTHENTICATED",
                    "message": "API key not valid. Please pass a valid API key.",
                }
            },
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    with pytest.raises(AppException) as exc:
        client.list_models(
            api_key="gemini-invalid",
            config_json={},
            default_timeout_seconds=30,
        )
    assert exc.value.payload.code == "provider_http_error"
    assert exc.value.payload.details["status_code"] == 401
    assert exc.value.payload.details["provider_error_type"] == "UNAUTHENTICATED"


def test_gemini_list_models_timeout(monkeypatch) -> None:
    client = GeminiClient()

    def fake_request(method, url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "request", fake_request)
    with pytest.raises(AppException) as exc:
        client.list_models(
            api_key="gemini-live-key",
            config_json={},
            default_timeout_seconds=30,
        )
    assert exc.value.payload.code == "provider_timeout"


def test_gemini_list_models_network_error(monkeypatch) -> None:
    client = GeminiClient()

    def fake_request(method, url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("dns failure")

    monkeypatch.setattr(httpx, "request", fake_request)
    with pytest.raises(AppException) as exc:
        client.list_models(
            api_key="gemini-live-key",
            config_json={},
            default_timeout_seconds=30,
        )
    assert exc.value.payload.code == "provider_network_error"


def test_gemini_generate_content_and_extract_usage(monkeypatch) -> None:
    client = GeminiClient()

    def fake_request(method, url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        assert method == "POST"
        assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        assert headers["x-goog-api-key"] == "gemini-live-key"
        assert json["generationConfig"]["maxOutputTokens"] == 256
        return _response(
            "POST",
            url,
            200,
            payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Resposta Gemini"}],
                        }
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 12,
                    "candidatesTokenCount": 8,
                    "totalTokenCount": 20,
                },
            },
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    payload = client.generate_content(
        api_key="gemini-live-key",
        model_name="models/gemini-2.5-flash",
        prompt="Oi",
        max_output_tokens=256,
        temperature=0.2,
        config_json={},
        default_timeout_seconds=30,
    )
    text = client.extract_generated_text(payload)
    input_tokens, output_tokens = client.extract_usage_tokens(
        payload=payload,
        prompt="Oi",
        output_text=text,
    )
    assert text == "Resposta Gemini"
    assert input_tokens == 12
    assert output_tokens == 8
