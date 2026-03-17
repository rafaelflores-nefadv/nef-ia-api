from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol


@dataclass(slots=True)
class ProviderExecutionResult:
    output_text: str
    input_tokens: int
    output_tokens: int
    raw_response: dict[str, Any]


class AiProviderClient(Protocol):
    def execute_prompt(
        self,
        *,
        prompt: str,
        model_name: str,
        max_tokens: int,
        temperature: float,
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
