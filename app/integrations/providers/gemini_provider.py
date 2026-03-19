from decimal import Decimal, ROUND_HALF_UP

from app.integrations.providers.base import ProviderExecutionResult
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
    ) -> ProviderExecutionResult:
        payload = self.client.generate_content(
            api_key=self.api_key,
            model_name=model_name,
            prompt=prompt,
            max_output_tokens=max_tokens,
            temperature=temperature,
            config_json=self.config_json,
            default_timeout_seconds=self.timeout_seconds,
        )
        output_text = self.client.extract_generated_text(payload)
        input_tokens, output_tokens = self.client.extract_usage_tokens(
            payload=payload,
            prompt=prompt,
            output_text=output_text,
        )
        return ProviderExecutionResult(
            output_text=output_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw_response=payload,
        )

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
