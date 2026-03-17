from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

from app.core.exceptions import AppException
from app.integrations.providers.base import ProviderExecutionResult


class OpenAIProvider:
    def __init__(self, *, api_key: str, timeout_seconds: int = 120, base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_url = base_url.rstrip("/")

    def execute_prompt(
        self,
        *,
        prompt: str,
        model_name: str,
        max_tokens: int,
        temperature: float,
    ) -> ProviderExecutionResult:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
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
                details={"provider": "openai"},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AppException(
                "Provider returned an error response.",
                status_code=502,
                code="provider_http_error",
                details={"provider": "openai", "status_code": exc.response.status_code},
            ) from exc
        except httpx.HTTPError as exc:
            raise AppException(
                "Failed to communicate with provider.",
                status_code=502,
                code="provider_network_error",
                details={"provider": "openai"},
            ) from exc

        data = response.json()
        output_text = self._extract_output_text(data)
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        input_tokens = int(usage.get("prompt_tokens") or self.count_tokens(prompt))
        output_tokens = int(usage.get("completion_tokens") or self.count_tokens(output_text))
        return ProviderExecutionResult(
            output_text=output_text,
            input_tokens=max(input_tokens, 0),
            output_tokens=max(output_tokens, 0),
            raw_response=data if isinstance(data, dict) else {"raw": data},
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
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AppException(
                "Provider response missing completion choices.",
                status_code=502,
                code="provider_invalid_response",
                details={"provider": "openai"},
            )

        first_choice = choices[0] if isinstance(choices[0], dict) else {}
        message = first_choice.get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict):
                    value = item.get("text")
                    if isinstance(value, str):
                        texts.append(value)
            if texts:
                return "\n".join(texts).strip()
        raise AppException(
            "Provider response has no textual content.",
            status_code=502,
            code="provider_empty_output",
            details={"provider": "openai"},
        )
