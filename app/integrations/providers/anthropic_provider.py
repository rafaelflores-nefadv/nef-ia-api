from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

import httpx

from app.core.exceptions import AppException
from app.integrations.providers.base import (
    ProviderExecutionResult,
    ProviderRequest,
    ProviderResponse,
    ProviderResponseUsage,
    provider_response_to_execution_result,
)
from app.services.providers.http_client_utils import (
    build_provider_transport_error_details,
    create_provider_request_trace,
    finalize_provider_request_trace,
    raise_provider_http_exception,
    summarize_provider_error_message,
)


class AnthropicProvider:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: int = 120,
        base_url: str = "https://api.anthropic.com",
        anthropic_version: str = "2023-06-01",
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_url = base_url.rstrip("/")
        self.anthropic_version = anthropic_version

    def execute_prompt(
        self,
        *,
        prompt: str,
        model_name: str,
        max_tokens: int,
        temperature: float,
        model_metadata: dict[str, Any] | None = None,
        client_request_id: str | None = None,
    ) -> ProviderExecutionResult:
        normalized_client_request_id = str(client_request_id or "").strip() or str(uuid4())
        provider_request = ProviderRequest(
            model=str(model_name or "").strip(),
            system_prompt="",
            user_prompt=str(prompt or ""),
            max_tokens=int(max_tokens),
            temperature=float(temperature),
            metadata=dict(model_metadata) if isinstance(model_metadata, dict) else {},
        )
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.anthropic_version,
            "Content-Type": "application/json",
            "X-Client-Request-Id": normalized_client_request_id,
        }
        payload: dict[str, Any] = {
            "model": provider_request.model,
            "max_tokens": provider_request.max_tokens,
            "temperature": provider_request.temperature,
            "messages": [{"role": "user", "content": provider_request.user_prompt}],
        }
        request_url = f"{self.base_url}/v1/messages"
        request_trace = create_provider_request_trace(
            provider_name="Anthropic",
            provider_slug="anthropic",
            model_name=model_name,
            model_slug=model_name,
            resolved_model_identifier=model_name,
            request_url=request_url,
            endpoint_name="messages",
            request_method="POST",
            request_timeout_seconds=self.timeout_seconds,
            request_payload=payload,
            request_headers=headers,
            extra_fields={
                "request_profile_resolved": "legacy_chat",
                "token_limit_param_used": "max_tokens",
                "retry_attempted": False,
                "retry_count": 0,
                "error_type": "",
            },
        )

        try:
            response = httpx.post(
                request_url,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            details = build_provider_transport_error_details(
                provider="anthropic",
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
                provider="anthropic",
                exc=exc,
                request_trace=request_trace,
            )
        except httpx.HTTPError as exc:
            details = build_provider_transport_error_details(
                provider="anthropic",
                transport_exception=exc,
                request_trace=request_trace,
            )
            raise AppException(
                summarize_provider_error_message(details=details),
                status_code=502,
                code="provider_network_error",
                details=details,
            ) from exc

        data = response.json()
        if not isinstance(data, dict):
            raise AppException(
                "Provider response is invalid.",
                status_code=502,
                code="provider_invalid_response",
                details={"provider": "anthropic"},
            )

        output_text = self._extract_output_text(data)
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        input_tokens = int(usage.get("input_tokens") or self.count_tokens(provider_request.user_prompt))
        output_tokens = int(usage.get("output_tokens") or self.count_tokens(output_text))
        finalized = finalize_provider_request_trace(request_trace)
        provider_debug = {
            **finalized,
            "provider_name": "Anthropic",
            "provider_slug": "anthropic",
            "model": provider_request.model,
            "request_profile_resolved": "legacy_chat",
            "token_limit_param_used": "max_tokens",
            "client_request_id": normalized_client_request_id,
            "provider_request_id": self._extract_request_id(response=response),
            "endpoint": "messages",
            "status_code": int(response.status_code),
            "retry_attempted": False,
            "retry_count": 0,
            "error_type": "",
        }
        raw_response = dict(data)
        raw_response["provider_debug"] = provider_debug
        provider_response = ProviderResponse(
            content=output_text,
            raw_response=raw_response,
            usage=ProviderResponseUsage(
                input_tokens=max(input_tokens, 0),
                output_tokens=max(output_tokens, 0),
            ),
            metadata={
                "model": provider_request.model,
                "provider_request_id": provider_debug.get("provider_request_id"),
            },
        )
        return provider_response_to_execution_result(provider_response)

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cost_input_per_1k_tokens: Decimal,
        cost_output_per_1k_tokens: Decimal,
    ) -> Decimal:
        input_cost = (Decimal(input_tokens) / Decimal(1000)) * Decimal(cost_input_per_1k_tokens)
        output_cost = (Decimal(output_tokens) / Decimal(1000)) * Decimal(cost_output_per_1k_tokens)
        return (input_cost + output_cost).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _extract_output_text(payload: dict[str, Any]) -> str:
        content = payload.get("content")
        if not isinstance(content, list) or not content:
            raise AppException(
                "Provider response has no textual content.",
                status_code=502,
                code="provider_empty_output",
                details={"provider": "anthropic"},
            )

        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").strip() != "text":
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())

        if not chunks:
            raise AppException(
                "Provider response has no textual content.",
                status_code=502,
                code="provider_empty_output",
                details={"provider": "anthropic"},
            )
        return "\n".join(chunks).strip()

    @staticmethod
    def _extract_request_id(*, response: httpx.Response) -> str:
        candidates = (
            "anthropic-request-id",
            "x-request-id",
            "request-id",
        )
        normalized_headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        for key in candidates:
            value = normalized_headers.get(key)
            if value:
                return value
        return ""
