from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from app.integrations.providers.base import (
    ProviderExecutionResult,
    ProviderRequest,
    ProviderResponse,
    ProviderResponseUsage,
    provider_response_to_execution_result,
)
from app.services.providers.gemini_client import GeminiClient


class GeminiProvider:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: int = 120,
        base_url: str = GeminiClient.DEFAULT_BASE_URL,
        api_version: str = GeminiClient.DEFAULT_API_VERSION,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.config_json = {
            "base_url": base_url.rstrip("/"),
            "api_version": str(api_version or GeminiClient.DEFAULT_API_VERSION).strip(),
        }
        self.client = GeminiClient()

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
        payload = self.client.generate_content(
            api_key=self.api_key,
            model_name=provider_request.model,
            prompt=provider_request.user_prompt,
            max_output_tokens=provider_request.max_tokens,
            temperature=provider_request.temperature,
            config_json=self.config_json,
            default_timeout_seconds=self.timeout_seconds,
            client_request_id=normalized_client_request_id,
        )
        output_text = self.client.extract_generated_text(payload)
        input_tokens, output_tokens = self.client.extract_usage_tokens(
            payload=payload,
            prompt=provider_request.user_prompt,
            output_text=output_text,
        )
        raw_response = dict(payload)
        provider_debug = raw_response.get("provider_debug")
        if isinstance(provider_debug, dict):
            provider_debug.setdefault("provider_name", "Gemini")
            provider_debug.setdefault("provider_slug", "gemini")
            provider_debug.setdefault("model", provider_request.model)
            provider_debug.setdefault("request_profile_resolved", "legacy_chat")
            provider_debug.setdefault("token_limit_param_used", "maxOutputTokens")
            provider_debug.setdefault("client_request_id", normalized_client_request_id)
            provider_debug.setdefault("retry_attempted", False)
            provider_debug.setdefault("retry_count", 0)
            provider_debug.setdefault("error_type", "")
            raw_response["provider_debug"] = provider_debug
        provider_response = ProviderResponse(
            content=output_text,
            raw_response=raw_response,
            usage=ProviderResponseUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            metadata={
                "model": provider_request.model,
                "provider_request_id": provider_debug.get("provider_request_id") if isinstance(provider_debug, dict) else "",
            },
        )
        return provider_response_to_execution_result(provider_response)

    def count_tokens(self, text: str) -> int:
        return self.client.count_tokens(text)

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
