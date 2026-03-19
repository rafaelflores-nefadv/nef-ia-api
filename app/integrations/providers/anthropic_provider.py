from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

from app.core.exceptions import AppException
from app.integrations.providers.base import ProviderExecutionResult


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
    ) -> ProviderExecutionResult:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.anthropic_version,
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }

        try:
            response = httpx.post(
                f"{self.base_url}/v1/messages",
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AppException(
                "Provider request timed out.",
                status_code=504,
                code="provider_timeout",
                details={"provider": "anthropic"},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AppException(
                "Provider returned an error response.",
                status_code=502,
                code="provider_http_error",
                details={"provider": "anthropic", "status_code": exc.response.status_code},
            ) from exc
        except httpx.HTTPError as exc:
            raise AppException(
                "Failed to communicate with provider.",
                status_code=502,
                code="provider_network_error",
                details={"provider": "anthropic"},
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
        input_tokens = int(usage.get("input_tokens") or self.count_tokens(prompt))
        output_tokens = int(usage.get("output_tokens") or self.count_tokens(output_text))
        return ProviderExecutionResult(
            output_text=output_text,
            input_tokens=max(input_tokens, 0),
            output_tokens=max(output_tokens, 0),
            raw_response=data,
        )

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
