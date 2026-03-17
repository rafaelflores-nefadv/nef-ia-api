from decimal import Decimal
from uuid import uuid4

from app.services.usage_service import UsageService


class FakeSession:
    def add(self, _: object) -> None:
        return None

    def flush(self) -> None:
        return None


class FakeUsageRepository:
    def __init__(self) -> None:
        self.items: list[object] = []

    def add(self, usage: object) -> object:
        self.items.append(usage)
        return usage


def test_calculate_estimated_cost_formula() -> None:
    cost = UsageService.calculate_estimated_cost(
        input_tokens=1500,
        output_tokens=500,
        cost_input_per_1k_tokens=Decimal("0.150000"),
        cost_output_per_1k_tokens=Decimal("0.600000"),
    )
    assert cost == Decimal("0.525000")


def test_register_usage_persists_row() -> None:
    service = UsageService(FakeSession())  # type: ignore[arg-type]
    fake_repo = FakeUsageRepository()
    service.usage_repository = fake_repo  # type: ignore[assignment]

    usage = service.register_usage(
        provider_id=uuid4(),
        model_id=uuid4(),
        execution_id=uuid4(),
        input_tokens=100,
        output_tokens=50,
        estimated_cost=Decimal("0.012500"),
    )

    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    assert usage.estimated_cost == Decimal("0.012500")
    assert len(fake_repo.items) == 1
