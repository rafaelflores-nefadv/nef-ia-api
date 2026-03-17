from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.operational import DjangoAiProviderUsage
from app.repositories.operational import ProviderUsageRepository


class UsageService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.usage_repository = ProviderUsageRepository(session)

    @staticmethod
    def calculate_estimated_cost(
        *,
        input_tokens: int,
        output_tokens: int,
        cost_input_per_1k_tokens: Decimal,
        cost_output_per_1k_tokens: Decimal,
    ) -> Decimal:
        input_cost = (Decimal(input_tokens) / Decimal(1000)) * Decimal(cost_input_per_1k_tokens)
        output_cost = (Decimal(output_tokens) / Decimal(1000)) * Decimal(cost_output_per_1k_tokens)
        return (input_cost + output_cost).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    def register_usage(
        self,
        *,
        provider_id: UUID,
        model_id: UUID,
        execution_id: UUID,
        input_tokens: int,
        output_tokens: int,
        estimated_cost: Decimal,
    ) -> DjangoAiProviderUsage:
        usage = DjangoAiProviderUsage(
            provider_id=provider_id,
            model_id=model_id,
            execution_id=execution_id,
            input_tokens=max(input_tokens, 0),
            output_tokens=max(output_tokens, 0),
            estimated_cost=estimated_cost,
        )
        self.usage_repository.add(usage)
        return usage
