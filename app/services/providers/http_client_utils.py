from __future__ import annotations

from typing import Any

import httpx

from app.core.exceptions import AppException


def resolve_timeout_seconds(*, config_json: dict[str, Any], default_timeout_seconds: int) -> int:
    raw_timeout = config_json.get("timeout_seconds")
    try:
        timeout_seconds = int(raw_timeout) if raw_timeout is not None else int(default_timeout_seconds)
    except (TypeError, ValueError):
        timeout_seconds = int(default_timeout_seconds)
    return max(timeout_seconds, 1)


def raise_provider_http_exception(*, provider: str, exc: httpx.HTTPStatusError) -> None:
    details: dict[str, Any] = {
        "provider": provider,
        "status_code": exc.response.status_code,
    }
    error_info = extract_response_error_info(exc.response)
    if error_info["type"]:
        details["provider_error_type"] = error_info["type"]
    if error_info["message"]:
        details["provider_error_message"] = error_info["message"]

    raise AppException(
        error_info["message"] or "Provider returned an error response.",
        status_code=502,
        code="provider_http_error",
        details=details,
    ) from exc


def extract_response_error_info(response: httpx.Response) -> dict[str, str]:
    payload = _safe_json(response)
    if not isinstance(payload, dict):
        return {"type": "", "message": ""}

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
        message = str(error_payload.get("message") or payload.get("message") or "").strip()
        return {"type": error_type, "message": message}

    # Fallback for other APIs.
    return {
        "type": str(payload.get("type") or "").strip(),
        "message": str(payload.get("message") or "").strip(),
    }


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None
