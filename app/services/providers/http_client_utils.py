from __future__ import annotations

import re
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Mapping

import httpx

from app.core.exceptions import AppException

SENSITIVE_FIELD_TOKENS = {
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "token",
    "access_token",
    "secret",
    "password",
    "credential",
    "x-api-key",
    "x-goog-api-key",
}
RELEVANT_RESPONSE_HEADERS = (
    "content-type",
    "x-request-id",
    "request-id",
    "openai-request-id",
    "anthropic-request-id",
    "x-amzn-requestid",
    "x-amz-request-id",
    "x-cloud-trace-context",
    "x-trace-id",
    "trace-id",
    "traceparent",
    "cf-ray",
)
REQUEST_ID_HEADER_CANDIDATES = (
    "x-request-id",
    "request-id",
    "openai-request-id",
    "anthropic-request-id",
    "x-amzn-requestid",
    "x-amz-request-id",
)
TRACE_ID_HEADER_CANDIDATES = (
    "x-trace-id",
    "trace-id",
    "traceparent",
    "x-cloud-trace-context",
    "cf-ray",
)
CLIENT_REQUEST_ID_HEADER_CANDIDATES = ("x-client-request-id",)
REDACTED_VALUE = "***redacted***"


def resolve_timeout_seconds(*, config_json: dict[str, Any], default_timeout_seconds: int) -> int:
    raw_timeout = config_json.get("timeout_seconds")
    try:
        timeout_seconds = int(raw_timeout) if raw_timeout is not None else int(default_timeout_seconds)
    except (TypeError, ValueError):
        timeout_seconds = int(default_timeout_seconds)
    return max(timeout_seconds, 1)


def raise_provider_http_exception(
    *,
    provider: str,
    exc: httpx.HTTPStatusError,
    request_trace: dict[str, Any] | None = None,
) -> None:
    details: dict[str, Any] = {
        "provider": provider,
        "status_code": exc.response.status_code,
        "http_status_code": exc.response.status_code,
    }
    details.update(build_provider_http_error_details(response=exc.response, request_trace=request_trace))
    message = summarize_provider_error_message(details=details)

    raise AppException(
        message,
        status_code=502,
        code="provider_http_error",
        details=details,
    ) from exc


def create_provider_request_trace(
    *,
    provider_name: str,
    provider_slug: str,
    model_name: str | None,
    model_slug: str | None,
    resolved_model_identifier: str | None,
    request_url: str,
    endpoint_name: str,
    request_method: str,
    request_timeout_seconds: int | float | None,
    request_payload: Any,
    request_headers: Mapping[str, Any] | None = None,
    extra_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "provider_name": str(provider_name or provider_slug or "").strip(),
        "provider_slug": str(provider_slug or "").strip().lower(),
        "model_name": str(model_name or "").strip() or str(model_slug or "").strip(),
        "model_slug": str(model_slug or "").strip(),
        "resolved_model_identifier": str(resolved_model_identifier or model_slug or model_name or "").strip(),
        "request_url": str(request_url or "").strip(),
        "endpoint_name": str(endpoint_name or "").strip(),
        "request_method": str(request_method or "").strip().upper(),
        "request_timeout_seconds": _coerce_timeout_seconds(request_timeout_seconds),
        "request_payload_sanitized": sanitize_provider_debug_payload(request_payload),
        "request_headers_sanitized": sanitize_provider_debug_headers(request_headers),
        "client_request_id": _extract_header_value(
            request_headers or {},
            candidates=CLIENT_REQUEST_ID_HEADER_CANDIDATES,
        ),
        "request_profile_resolved": "",
        "token_limit_param_used": "",
        "retry_attempted": False,
        "retry_count": 0,
        "error_type": "",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "_perf_started_at": perf_counter(),
    }
    if isinstance(extra_fields, Mapping):
        for key, value in extra_fields.items():
            trace[str(key)] = value
    return trace


def finalize_provider_request_trace(trace: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(trace, dict):
        return {}
    result = {key: value for key, value in trace.items() if key != "_perf_started_at"}
    started = trace.get("_perf_started_at")
    now = perf_counter()
    if isinstance(started, (int, float)):
        result["duration_ms"] = max(int((now - float(started)) * 1000), 0)
    else:
        result["duration_ms"] = 0
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    return result


def build_provider_http_error_details(
    *,
    response: httpx.Response,
    request_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response_body_json = _safe_json(response)
    response_body_text = _safe_response_text(response)
    error_info = extract_response_error_info(response)

    details: dict[str, Any] = {
        **finalize_provider_request_trace(request_trace),
        "http_status_code": response.status_code,
        "status_code": response.status_code,
        "provider_error_message": error_info["message"],
        "provider_error_type": error_info["type"],
        "provider_error_code": error_info["code"],
        "provider_request_id": _extract_header_value(
            response.headers,
            candidates=REQUEST_ID_HEADER_CANDIDATES,
        ),
        "provider_trace_id": _extract_header_value(
            response.headers,
            candidates=TRACE_ID_HEADER_CANDIDATES,
        ),
        "response_headers_relevantes": _extract_relevant_response_headers(response.headers),
        "response_body_text": response_body_text,
        "response_body_json": response_body_json if isinstance(response_body_json, (dict, list)) else None,
        "transport_error_class": "",
        "transport_error_message": "",
    }
    details["endpoint"] = str(details.get("endpoint_name") or "")
    details["provider_error_classification"] = classify_provider_http_error(details=details)
    details["error_type"] = details["provider_error_classification"]
    return details


def build_provider_transport_error_details(
    *,
    provider: str,
    transport_exception: Exception,
    request_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        **finalize_provider_request_trace(request_trace),
        "provider": provider,
        "http_status_code": None,
        "provider_error_message": "",
        "provider_error_type": "",
        "provider_error_code": "",
        "provider_request_id": "",
        "provider_trace_id": "",
        "response_headers_relevantes": {},
        "response_body_text": "",
        "response_body_json": None,
        "transport_error_class": transport_exception.__class__.__name__,
        "transport_error_message": str(transport_exception or "").strip(),
    }
    details["endpoint"] = str(details.get("endpoint_name") or "")
    details["provider_error_classification"] = classify_provider_transport_error(
        transport_error_class=details["transport_error_class"],
    )
    details["error_type"] = details["provider_error_classification"]
    return details


def sanitize_provider_debug_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, nested in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                sanitized[key_text] = REDACTED_VALUE
            else:
                sanitized[key_text] = sanitize_provider_debug_payload(nested)
        return sanitized
    if isinstance(value, list):
        return [sanitize_provider_debug_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_provider_debug_payload(item) for item in value]
    if isinstance(value, str):
        return _sanitize_inline_secret(value)
    return value


def sanitize_provider_debug_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    if headers is None:
        return {}
    sanitized: dict[str, str] = {}
    for raw_key, raw_value in headers.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        value = str(raw_value or "").strip()
        sanitized[key] = REDACTED_VALUE if _is_sensitive_key(key) else _sanitize_inline_secret(value)
    return sanitized


def extract_response_error_info(response: httpx.Response) -> dict[str, str]:
    payload = _safe_json(response)
    body_text = _safe_response_text(response)
    if not isinstance(payload, dict):
        return {"type": "", "message": "", "code": ""}

    # OpenAI-like: {"error": {"type": "...", "message": "..."}}
    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        error_type = str(
            error_payload.get("type")
            or error_payload.get("status")
            or payload.get("type")
            or payload.get("status")
            or ""
        ).strip()
        error_code = str(error_payload.get("code") or payload.get("code") or "").strip()
        message = str(error_payload.get("message") or payload.get("message") or "").strip()
        if not message and body_text:
            message = body_text
        return {"type": error_type, "message": message, "code": error_code}

    # Fallback for other APIs.
    fallback_message = str(payload.get("message") or "").strip()
    if not fallback_message and body_text:
        fallback_message = body_text
    return {
        "type": str(payload.get("type") or "").strip(),
        "message": fallback_message,
        "code": str(payload.get("code") or "").strip(),
    }


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _safe_response_text(response: httpx.Response, *, max_chars: int = 30000) -> str:
    try:
        text = str(response.text or "").strip()
    except Exception:
        return ""
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}...[truncated]"


def _extract_relevant_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
    filtered: dict[str, str] = {}
    for key in RELEVANT_RESPONSE_HEADERS:
        value = normalized_headers.get(key)
        if value:
            filtered[key] = value
    return filtered


def _extract_header_value(headers: Mapping[str, str], *, candidates: tuple[str, ...]) -> str:
    normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
    for key in candidates:
        value = normalized_headers.get(key.lower())
        if value:
            return value
    return ""


def _coerce_timeout_seconds(value: int | float | None) -> int:
    try:
        timeout_seconds = int(float(value if value is not None else 0))
    except (TypeError, ValueError):
        timeout_seconds = 0
    return max(timeout_seconds, 0)


def _is_sensitive_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    if not normalized:
        return False
    compact = re.sub(r"[^a-z0-9]+", "_", normalized)
    if compact in SENSITIVE_FIELD_TOKENS:
        return True
    return any(token in compact for token in SENSITIVE_FIELD_TOKENS)


def _sanitize_inline_secret(value: str) -> str:
    token = str(value or "")
    if not token:
        return ""
    if token.lower().startswith("bearer "):
        return "Bearer ***redacted***"
    token = re.sub(r"(?i)bearer\s+[a-z0-9._\-]+", "Bearer ***redacted***", token)
    return token


def classify_provider_http_error(*, details: Mapping[str, Any]) -> str:
    http_status = details.get("http_status_code")
    try:
        status = int(http_status) if http_status is not None else None
    except (TypeError, ValueError):
        status = None

    provider_error_type = str(details.get("provider_error_type") or "").strip().lower()
    provider_error_code = str(details.get("provider_error_code") or "").strip().lower()
    provider_error_message = str(details.get("provider_error_message") or "").strip().lower()
    body_json = details.get("response_body_json")
    body_text = str(details.get("response_body_text") or "").strip()

    if status in {401, 403}:
        return "provider_auth_error"
    if status == 429:
        return "provider_rate_limit"
    if status in {400, 422} and _looks_like_unsupported_parameter(
        message=provider_error_message,
        error_type=provider_error_type,
        error_code=provider_error_code,
        body_json=body_json,
    ):
        return "provider_unsupported_parameter"
    if _looks_like_unsupported_model(
        message=provider_error_message,
        error_type=provider_error_type,
        error_code=provider_error_code,
    ):
        return "provider_unsupported_model"
    if status in {400, 422}:
        if body_json is None and body_text:
            return "provider_non_json_error"
        return "provider_invalid_request"
    if status == 404 and _looks_like_model_lookup_error(message=provider_error_message):
        return "provider_unsupported_model"
    if body_json is None and body_text:
        return "provider_non_json_error"
    return "provider_http_error"


def classify_provider_transport_error(*, transport_error_class: str) -> str:
    normalized_class = str(transport_error_class or "").strip().lower()
    if "timeout" in normalized_class:
        return "provider_timeout"
    return "provider_connection_error"


def summarize_provider_error_message(*, details: Mapping[str, Any]) -> str:
    classification = str(details.get("provider_error_classification") or "").strip()
    provider_message = str(details.get("provider_error_message") or "").strip()
    transport_error_class = str(details.get("transport_error_class") or "").strip()
    transport_error_message = str(details.get("transport_error_message") or "").strip()

    status = details.get("http_status_code")
    try:
        http_status = int(status) if status is not None else None
    except (TypeError, ValueError):
        http_status = None

    timeout_seconds = details.get("request_timeout_seconds")
    try:
        timeout_suffix = f" after {int(timeout_seconds)}s" if timeout_seconds is not None else ""
    except (TypeError, ValueError):
        timeout_suffix = ""

    if classification == "provider_timeout":
        return f"Provider timeout{timeout_suffix}".strip()
    if classification == "provider_connection_error":
        if transport_error_message:
            return f"Provider connection error: {transport_error_message}"
        if transport_error_class:
            return f"Provider connection error: {transport_error_class}"
        return "Provider connection error"
    if http_status is None:
        return provider_message or "Provider returned an error response."
    if provider_message:
        return f"Provider HTTP {http_status}: {provider_message}"
    if classification == "provider_auth_error":
        return f"Provider HTTP {http_status}: invalid authentication"
    if classification == "provider_rate_limit":
        return f"Provider HTTP {http_status}: rate limit exceeded"
    if classification == "provider_unsupported_model":
        return f"Provider HTTP {http_status}: model not found"
    if classification == "provider_unsupported_parameter":
        return f"Provider HTTP {http_status}: unsupported parameter"
    if classification == "provider_invalid_request":
        return f"Provider HTTP {http_status}: invalid request"
    if classification == "provider_non_json_error":
        return f"Provider HTTP {http_status}: non-JSON error response"
    return f"Provider HTTP {http_status}: request failed"


def _looks_like_unsupported_model(*, message: str, error_type: str, error_code: str) -> bool:
    haystack = " ".join(part for part in (message, error_type, error_code) if part).lower()
    if not haystack:
        return False
    if "parameter" in haystack:
        return False
    return (
        "model" in haystack
        and (
            "not found" in haystack
            or "does not exist" in haystack
            or "unsupported" in haystack
            or "invalid" in haystack
            or "unknown" in haystack
        )
    )


def _looks_like_model_lookup_error(*, message: str) -> bool:
    normalized = str(message or "").strip().lower()
    return "model" in normalized and ("not found" in normalized or "does not exist" in normalized)


def _looks_like_unsupported_parameter(
    *,
    message: str,
    error_type: str,
    error_code: str,
    body_json: Any,
) -> bool:
    haystack = " ".join(part for part in (message, error_type, error_code) if part).lower()
    if not haystack and isinstance(body_json, dict):
        haystack = str(body_json).lower()
    return "unsupported parameter" in haystack or "unsupported_parameter" in haystack
