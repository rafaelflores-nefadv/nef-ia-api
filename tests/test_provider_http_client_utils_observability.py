import httpx
import pytest

from app.core.exceptions import AppException
from app.services.providers.http_client_utils import (
    build_provider_transport_error_details,
    create_provider_request_trace,
    raise_provider_http_exception,
    sanitize_provider_debug_payload,
    summarize_provider_error_message,
)


def _build_request_trace() -> dict:
    return create_provider_request_trace(
        provider_name="OpenAI",
        provider_slug="openai",
        model_name="gpt-5",
        model_slug="gpt-5",
        resolved_model_identifier="gpt-5",
        request_url="https://api.openai.com/v1/chat/completions",
        endpoint_name="chat_completions",
        request_method="POST",
        request_timeout_seconds=60,
        request_payload={
            "model": "gpt-5",
            "api_key": "sk-live-secret",
            "authorization": "Bearer sk-live-secret",
            "messages": [{"role": "user", "content": "olá"}],
        },
        request_headers={
            "Authorization": "Bearer sk-live-secret",
            "x-api-key": "live-secret",
        },
    )


def _http_status_error(
    *,
    status_code: int,
    json_payload: dict | None = None,
    text_payload: str | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    if json_payload is not None:
        response = httpx.Response(status_code, json=json_payload, headers=headers, request=request)
    else:
        response = httpx.Response(status_code, text=text_payload or "", headers=headers, request=request)
    return httpx.HTTPStatusError("provider error", request=request, response=response)


def test_http_400_json_error_includes_body_and_classification() -> None:
    trace = _build_request_trace()
    exc = _http_status_error(
        status_code=400,
        json_payload={
            "error": {
                "type": "invalid_request_error",
                "code": "invalid_parameter",
                "message": "unsupported parameter response_format",
            }
        },
        headers={"x-request-id": "req_123"},
    )

    with pytest.raises(AppException) as raised:
        raise_provider_http_exception(provider="openai", exc=exc, request_trace=trace)

    details = raised.value.payload.details or {}
    assert raised.value.payload.code == "provider_http_error"
    assert details["status_code"] == 400
    assert details["provider_error_classification"] == "provider_unsupported_parameter"
    assert details["provider_error_message"] == "unsupported parameter response_format"
    assert details["provider_error_code"] == "invalid_parameter"
    assert details["provider_request_id"] == "req_123"
    assert details["response_body_json"]["error"]["type"] == "invalid_request_error"
    assert details["request_payload_sanitized"]["api_key"] == "***redacted***"


def test_http_401_is_classified_as_auth_error() -> None:
    trace = _build_request_trace()
    exc = _http_status_error(
        status_code=401,
        json_payload={"error": {"type": "authentication_error", "message": "invalid authentication"}},
    )

    with pytest.raises(AppException) as raised:
        raise_provider_http_exception(provider="openai", exc=exc, request_trace=trace)

    details = raised.value.payload.details or {}
    assert details["provider_error_classification"] == "provider_auth_error"
    assert "Provider HTTP 401" in raised.value.payload.message


def test_http_404_model_not_found_is_classified_as_unsupported_model() -> None:
    trace = _build_request_trace()
    exc = _http_status_error(
        status_code=404,
        json_payload={"error": {"type": "invalid_request_error", "message": "The model `gpt-5-x` does not exist"}},
    )

    with pytest.raises(AppException) as raised:
        raise_provider_http_exception(provider="openai", exc=exc, request_trace=trace)

    details = raised.value.payload.details or {}
    assert details["provider_error_classification"] == "provider_unsupported_model"
    assert details["provider_error_message"] == "The model `gpt-5-x` does not exist"


def test_http_429_is_classified_as_rate_limit() -> None:
    trace = _build_request_trace()
    exc = _http_status_error(
        status_code=429,
        json_payload={"error": {"type": "rate_limit_error", "message": "rate limit exceeded"}},
    )

    with pytest.raises(AppException) as raised:
        raise_provider_http_exception(provider="openai", exc=exc, request_trace=trace)

    details = raised.value.payload.details or {}
    assert details["provider_error_classification"] == "provider_rate_limit"
    assert "Provider HTTP 429" in raised.value.payload.message


def test_transport_timeout_is_classified_and_summarized() -> None:
    trace = _build_request_trace()
    timeout_exc = httpx.ReadTimeout("timeout", request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))

    details = build_provider_transport_error_details(
        provider="openai",
        transport_exception=timeout_exc,
        request_trace=trace,
    )

    assert details["provider_error_classification"] == "provider_timeout"
    assert summarize_provider_error_message(details=details) == "Provider timeout after 60s"


def test_transport_connection_error_is_classified() -> None:
    trace = _build_request_trace()
    conn_exc = httpx.ConnectError("connection refused", request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))

    details = build_provider_transport_error_details(
        provider="openai",
        transport_exception=conn_exc,
        request_trace=trace,
    )

    assert details["provider_error_classification"] == "provider_connection_error"
    assert "Provider connection error" in summarize_provider_error_message(details=details)


def test_http_error_with_plain_text_body_is_captured() -> None:
    trace = _build_request_trace()
    exc = _http_status_error(
        status_code=502,
        text_payload="gateway failed upstream",
        headers={"content-type": "text/plain"},
    )

    with pytest.raises(AppException) as raised:
        raise_provider_http_exception(provider="openai", exc=exc, request_trace=trace)

    details = raised.value.payload.details or {}
    assert details["provider_error_classification"] == "provider_non_json_error"
    assert details["response_body_json"] is None
    assert "gateway failed upstream" in details["response_body_text"]


def test_sanitize_provider_payload_masks_credentials_recursively() -> None:
    payload = {
        "api_key": "sk-live-secret",
        "nested": {
            "authorization": "Bearer sk-live-secret",
            "access_token": "token-123",
            "safe": "ok",
        },
        "messages": [{"role": "user", "content": "hello"}],
    }

    sanitized = sanitize_provider_debug_payload(payload)

    assert sanitized["api_key"] == "***redacted***"
    assert sanitized["nested"]["authorization"] == "***redacted***"
    assert sanitized["nested"]["access_token"] == "***redacted***"
    assert sanitized["nested"]["safe"] == "ok"
