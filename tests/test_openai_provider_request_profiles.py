import httpx
import pytest

from app.core.exceptions import AppException
from app.integrations.providers.openai_provider import OpenAIProvider


def _ok_response(url: str) -> httpx.Response:
    request = httpx.Request("POST", url)
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        },
        request=request,
    )


def test_openai_legacy_model_uses_max_tokens(monkeypatch) -> None:
    provider = OpenAIProvider(api_key="sk-live")
    captured: dict = {}

    def fake_post(url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _ok_response(url)

    monkeypatch.setattr(httpx, "post", fake_post)
    result = provider.execute_prompt(
        prompt="teste",
        model_name="gpt-4.1-mini",
        max_tokens=700,
        temperature=0.2,
    )

    assert result.output_text == "ok"
    assert captured["json"]["max_tokens"] == 700
    assert "max_completion_tokens" not in captured["json"]
    assert "X-Client-Request-Id" in captured["headers"]
    assert isinstance(result.raw_response.get("provider_debug"), dict)
    assert result.raw_response["provider_debug"]["request_profile_resolved"] == "legacy_chat"
    assert result.raw_response["provider_debug"]["token_limit_param_used"] == "max_tokens"


def test_openai_gpt5_model_uses_max_completion_tokens_by_name_inference(monkeypatch) -> None:
    provider = OpenAIProvider(api_key="sk-live")
    captured: dict = {}

    def fake_post(url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        captured["json"] = json
        return _ok_response(url)

    monkeypatch.setattr(httpx, "post", fake_post)
    provider.execute_prompt(
        prompt="teste",
        model_name="gpt-5-mini",
        max_tokens=900,
        temperature=0.1,
    )

    assert captured["json"]["max_completion_tokens"] == 900
    assert "max_tokens" not in captured["json"]


def test_openai_gpt54_model_uses_max_completion_tokens(monkeypatch) -> None:
    provider = OpenAIProvider(api_key="sk-live")
    captured: dict = {}

    def fake_post(url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        captured["json"] = json
        return _ok_response(url)

    monkeypatch.setattr(httpx, "post", fake_post)
    provider.execute_prompt(
        prompt="teste",
        model_name="gpt-5.4-mini",
        max_tokens=512,
        temperature=0.3,
    )

    assert captured["json"]["max_completion_tokens"] == 512
    assert "max_tokens" not in captured["json"]


def test_openai_metadata_can_force_max_completion_tokens_for_legacy_model(monkeypatch) -> None:
    provider = OpenAIProvider(api_key="sk-live")
    captured: dict = {}

    def fake_post(url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        captured["json"] = json
        return _ok_response(url)

    monkeypatch.setattr(httpx, "post", fake_post)
    provider.execute_prompt(
        prompt="teste",
        model_name="gpt-4.1-mini",
        max_tokens=400,
        temperature=0.2,
        model_metadata={"token_limit_param": "max_completion_tokens"},
    )

    assert captured["json"]["max_completion_tokens"] == 400
    assert "max_tokens" not in captured["json"]


def test_openai_metadata_has_priority_over_name_inference(monkeypatch) -> None:
    provider = OpenAIProvider(api_key="sk-live")
    captured: dict = {}

    def fake_post(url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        captured["json"] = json
        return _ok_response(url)

    monkeypatch.setattr(httpx, "post", fake_post)
    provider.execute_prompt(
        prompt="teste",
        model_name="gpt-5-mini",
        max_tokens=321,
        temperature=0.2,
        model_metadata={"request_profile": "legacy_chat"},
    )

    assert captured["json"]["max_tokens"] == 321
    assert "max_completion_tokens" not in captured["json"]


def test_openai_unsupported_parameter_error_is_classified_without_model_mismatch(monkeypatch) -> None:
    provider = OpenAIProvider(api_key="sk-live")
    calls = {"count": 0}

    def fake_post(url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        request = httpx.Request("POST", url)
        return httpx.Response(
            400,
            json={
                "error": {
                    "type": "invalid_request_error",
                    "code": "unsupported_parameter",
                    "message": (
                        "Unsupported parameter: 'max_tokens' is not supported with this model. "
                        "Use 'max_completion_tokens' instead."
                    ),
                }
            },
            headers={"x-request-id": "req-openai-123"},
            request=request,
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(AppException) as raised:
        provider.execute_prompt(
            prompt="teste",
            model_name="gpt-5-mini",
            max_tokens=321,
            temperature=0.2,
            model_metadata={"request_profile": "legacy_chat"},
            client_request_id="exec-123-row-2",
        )

    details = raised.value.payload.details or {}
    assert raised.value.payload.code == "provider_http_error"
    assert details["provider_error_classification"] == "provider_unsupported_parameter"
    assert details["provider_error_classification"] != "provider_unsupported_model"
    assert details["provider_request_id"] == "req-openai-123"
    assert details["client_request_id"] == "exec-123-row-2"
    assert details["retry_attempted"] is True
    assert details["retry_count"] == 1
    assert calls["count"] == 2


def test_openai_safe_retry_rewrites_payload_and_succeeds(monkeypatch) -> None:
    provider = OpenAIProvider(api_key="sk-live")
    payloads: list[dict] = []

    def fake_post(url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        payloads.append(dict(json))
        request = httpx.Request("POST", url)
        if len(payloads) == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "type": "invalid_request_error",
                        "code": "unsupported_parameter",
                        "message": "Unsupported parameter: 'max_tokens' is not supported with this model.",
                    }
                },
                request=request,
                headers={"x-request-id": "req-retry-1"},
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok after retry"}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4},
            },
            request=request,
            headers={"x-request-id": "req-retry-2"},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    result = provider.execute_prompt(
        prompt="teste",
        model_name="gpt-5-mini",
        max_tokens=333,
        temperature=0.2,
        model_metadata={"request_profile": "legacy_chat"},
        client_request_id="retry-exec-123",
    )

    assert len(payloads) == 2
    assert payloads[0]["max_tokens"] == 333
    assert "max_completion_tokens" not in payloads[0]
    assert "max_tokens" not in payloads[1]
    assert payloads[1]["max_completion_tokens"] == 333
    provider_debug = result.raw_response.get("provider_debug") or {}
    assert provider_debug["retry_attempted"] is True
    assert provider_debug["retry_count"] == 1
    assert provider_debug["token_limit_param_used"] == "max_completion_tokens"
    assert provider_debug["client_request_id"] == "retry-exec-123"


def test_openai_no_retry_for_auth_error(monkeypatch) -> None:
    provider = OpenAIProvider(api_key="sk-live")
    calls = {"count": 0}

    def fake_post(url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        request = httpx.Request("POST", url)
        return httpx.Response(
            401,
            json={"error": {"type": "authentication_error", "message": "invalid api key"}},
            request=request,
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(AppException) as raised:
        provider.execute_prompt(
            prompt="teste",
            model_name="gpt-5-mini",
            max_tokens=200,
            temperature=0.3,
            model_metadata={"request_profile": "legacy_chat"},
        )

    details = raised.value.payload.details or {}
    assert calls["count"] == 1
    assert details["provider_error_classification"] == "provider_auth_error"
    assert details["retry_attempted"] is False
