from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol


@dataclass(slots=True)
class ProviderRequest:
    model: str
    system_prompt: str
    user_prompt: str
    max_tokens: int
    temperature: float
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class ProviderResponseUsage:
    input_tokens: int
    output_tokens: int


@dataclass(slots=True)
class ProviderResponse:
    content: str
    raw_response: dict[str, Any]
    usage: ProviderResponseUsage
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class ProviderExecutionResult:
    output_text: str
    input_tokens: int
    output_tokens: int
    raw_response: dict[str, Any]


def provider_response_to_execution_result(response: ProviderResponse) -> ProviderExecutionResult:
    usage = response.usage
    return ProviderExecutionResult(
        output_text=str(response.content or ""),
        input_tokens=max(int(usage.input_tokens or 0), 0),
        output_tokens=max(int(usage.output_tokens or 0), 0),
        raw_response=response.raw_response if isinstance(response.raw_response, dict) else {},
    )


class AiProviderClient(Protocol):
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
        ...

    def count_tokens(self, text: str) -> int:
        ...

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cost_input_per_1k_tokens: Decimal,
        cost_output_per_1k_tokens: Decimal,
    ) -> Decimal:
        ...
