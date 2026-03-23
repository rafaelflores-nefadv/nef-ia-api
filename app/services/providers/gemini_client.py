from __future__ import annotations

from typing import Any

import httpx

from app.core.exceptions import AppException
from app.services.providers.http_client_utils import (
    build_provider_transport_error_details,
    create_provider_request_trace,
    finalize_provider_request_trace,
    raise_provider_http_exception,
    resolve_timeout_seconds,
    summarize_provider_error_message,
)


class GeminiClient:
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
    DEFAULT_API_VERSION = "v1beta"

    def list_models(
        self,
        *,
        api_key: str,
        config_json: dict[str, Any],
        default_timeout_seconds: int,
    ) -> list[dict[str, Any]]:
        payload = self._request_json(
            method="GET",
            path="/models",
            api_key=api_key,
            config_json=config_json,
            default_timeout_seconds=default_timeout_seconds,
            model_name=None,
        )
        items = payload.get("models")
        if not isinstance(items, list):
            raise AppException(
                "Provider response has no models list.",
                status_code=502,
                code="provider_invalid_response",
                details={"provider": "gemini"},
            )
        return [item for item in items if isinstance(item, dict)]

    def generate_content(
        self,
        *,
        api_key: str,
        model_name: str,
        prompt: str,
        max_output_tokens: int,
        temperature: float,
        config_json: dict[str, Any],
        default_timeout_seconds: int,
        client_request_id: str | None = None,
    ) -> dict[str, Any]:
        model_id = self._normalize_model_id(model_name)
        generation_config: dict[str, Any] = {}
        if max_output_tokens > 0:
            generation_config["maxOutputTokens"] = int(max_output_tokens)
        generation_config["temperature"] = float(temperature)

        payload = self._request_json(
            method="POST",
            path=f"/models/{model_id}:generateContent",
            api_key=api_key,
            config_json=config_json,
            default_timeout_seconds=default_timeout_seconds,
            model_name=model_name,
            client_request_id=client_request_id,
            json_body={
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
                "generationConfig": generation_config,
            },
        )
        return payload

    def extract_generated_text(self, payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            raise AppException(
                "Provider response has no textual content.",
                status_code=502,
                code="provider_empty_output",
                details={"provider": "gemini"},
            )

        chunks: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())

        if not chunks:
            raise AppException(
                "Provider response has no textual content.",
                status_code=502,
                code="provider_empty_output",
                details={"provider": "gemini"},
            )
        return "\n".join(chunks).strip()

    def extract_usage_tokens(
        self,
        *,
        payload: dict[str, Any],
        prompt: str,
        output_text: str,
    ) -> tuple[int, int]:
        usage = payload.get("usageMetadata")
        usage_json = usage if isinstance(usage, dict) else {}

        input_tokens = self._coerce_int(
            usage_json.get("promptTokenCount")
            or usage_json.get("inputTokenCount")
        )
        output_tokens = self._coerce_int(
            usage_json.get("candidatesTokenCount")
            or usage_json.get("outputTokenCount")
        )

        if input_tokens is None:
            input_tokens = self.count_tokens(prompt)
        if output_tokens is None:
            output_tokens = self.count_tokens(output_text)
        return max(input_tokens, 0), max(output_tokens, 0)

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        api_key: str,
        model_name: str | None,
        config_json: dict[str, Any],
        default_timeout_seconds: int,
        client_request_id: str | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        timeout_seconds = resolve_timeout_seconds(
            config_json=config_json,
            default_timeout_seconds=default_timeout_seconds,
        )
        api_base = self._resolve_api_base(config_json=config_json)

        headers = {
            "x-goog-api-key": api_key,
            "accept": "application/json",
            "content-type": "application/json",
        }
        normalized_client_request_id = str(client_request_id or "").strip()
        if normalized_client_request_id:
            headers["X-Client-Request-Id"] = normalized_client_request_id
        request_url = f"{api_base}{path}"
        request_trace = create_provider_request_trace(
            provider_name="Gemini",
            provider_slug="gemini",
            model_name=model_name,
            model_slug=model_name,
            resolved_model_identifier=model_name,
            request_url=request_url,
            endpoint_name=path.strip("/"),
            request_method=method.upper(),
            request_timeout_seconds=timeout_seconds,
            request_payload=json_body,
            request_headers=headers,
            extra_fields={
                "request_profile_resolved": "legacy_chat",
                "token_limit_param_used": "maxOutputTokens",
                "retry_attempted": False,
                "retry_count": 0,
                "error_type": "",
            },
        )

        try:
            response = httpx.request(
                method=method.upper(),
                url=request_url,
                headers=headers,
                json=json_body,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            details = build_provider_transport_error_details(
                provider="gemini",
                transport_exception=exc,
                request_trace=request_trace,
            )
            raise AppException(
                summarize_provider_error_message(details=details),
                status_code=504,
                code="provider_timeout",
                details=details,
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise_provider_http_exception(
                provider="gemini",
                exc=exc,
                request_trace=request_trace,
            )
        except httpx.HTTPError as exc:
            details = build_provider_transport_error_details(
                provider="gemini",
                transport_exception=exc,
                request_trace=request_trace,
            )
            raise AppException(
                summarize_provider_error_message(details=details),
                status_code=502,
                code="provider_network_error",
                details=details,
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise AppException(
                "Provider response is invalid.",
                status_code=502,
                code="provider_invalid_response",
                details={"provider": "gemini"},
            ) from exc

        if not isinstance(payload, dict):
            raise AppException(
                "Provider response is invalid.",
                status_code=502,
                code="provider_invalid_response",
                details={"provider": "gemini"},
            )
        provider_request_id = ""
        for header_name in ("x-request-id", "request-id"):
            header_value = response.headers.get(header_name)
            if header_value:
                provider_request_id = str(header_value)
                break
        payload["provider_debug"] = {
            **finalize_provider_request_trace(request_trace),
            "provider_name": "Gemini",
            "provider_slug": "gemini",
            "model": str(model_name or ""),
            "request_profile_resolved": "legacy_chat",
            "token_limit_param_used": "maxOutputTokens",
            "client_request_id": normalized_client_request_id,
            "provider_request_id": provider_request_id,
            "endpoint": path.strip("/"),
            "status_code": int(response.status_code),
            "retry_attempted": False,
            "retry_count": 0,
            "error_type": "",
        }
        return payload

    def _resolve_api_base(self, *, config_json: dict[str, Any]) -> str:
        raw_base_url = str(config_json.get("base_url") or self.DEFAULT_BASE_URL).strip().rstrip("/")
        if not raw_base_url:
            raw_base_url = self.DEFAULT_BASE_URL

        api_version = str(config_json.get("api_version") or self.DEFAULT_API_VERSION).strip().strip("/")
        if not api_version:
            api_version = self.DEFAULT_API_VERSION

        if raw_base_url.endswith(f"/{api_version}"):
            return raw_base_url
        return f"{raw_base_url}/{api_version}"

    @staticmethod
    def _normalize_model_id(value: str) -> str:
        model_id = str(value or "").strip()
        if not model_id:
            raise AppException(
                "Configured model slug is invalid.",
                status_code=422,
                code="provider_model_invalid",
                details={"provider": "gemini"},
            )
        if model_id.startswith("models/"):
            model_id = model_id[len("models/") :]
        return model_id

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if value in {None, ""}:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
