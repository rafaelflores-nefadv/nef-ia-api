import os
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.services.api_client import ApiResponse
from core.services.provider_models_service import ProviderModelsService
from models_catalog.catalog import KnownModel


class FakeFastAPIClient:
    def __init__(self, *, available_response: ApiResponse, catalog_response: ApiResponse | None = None) -> None:
        self.available_response = available_response
        self.catalog_response = catalog_response
        self.calls: list[tuple[str, str]] = []

    def get_admin_headers(self):  # type: ignore[no-untyped-def]
        return {"Authorization": "Bearer test-token"}

    def request_json(self, **kwargs):  # type: ignore[no-untyped-def]
        method = str(kwargs.get("method") or "").upper()
        path = str(kwargs.get("path") or "")
        self.calls.append((method, path))
        if path.endswith("/available-models"):
            return self.available_response
        if path.endswith("/models") and self.catalog_response is not None:
            return self.catalog_response
        raise AssertionError(f"Unexpected request: {method} {path}")


def _provider(slug: str = "openai"):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        id=1,
        slug=slug,
        fastapi_provider_id=uuid4(),
    )


def test_available_models_enriches_missing_metadata_with_known_fallback(monkeypatch) -> None:
    provider = _provider(slug="openai")
    available_payload = [
        {
            "id": str(uuid4()),
            "model_name": "gpt-4.1",
            "model_slug": "gpt-4.1",
            "context_window": None,
            "cost_input_per_1k_tokens": None,
            "cost_output_per_1k_tokens": None,
            "description": "",
            "is_registered": False,
        }
    ]
    service = ProviderModelsService()
    service.client = FakeFastAPIClient(available_response=ApiResponse(status_code=200, data=available_payload))  # type: ignore[assignment]
    service.admin_token = "test-token"

    monkeypatch.setattr(
        "core.services.provider_models_service.get_known_models",
        lambda slug: [
            KnownModel(
                key="gpt-4-1",
                label="GPT-4.1",
                name="GPT-4.1",
                slug="gpt-4-1",
                context_window=128000,
                input_cost_per_1k=Decimal("0.002000"),
                output_cost_per_1k=Decimal("0.008000"),
                description="Modelo conhecido local para fallback.",
            )
        ],
    )

    payload = service.get_available_models(provider=provider)
    item = payload["items"][0]

    assert payload["source"] == "api_provider"
    assert item["slug"] == "gpt-4.1"
    assert item["context_window"] == 128000
    assert item["input_cost_per_1k"] == Decimal("0.002000")
    assert item["output_cost_per_1k"] == Decimal("0.008000")
    assert item["description"] == "Modelo conhecido local para fallback."


def test_available_models_preserves_api_metadata_when_already_present(monkeypatch) -> None:
    provider = _provider(slug="openai")
    available_payload = [
        {
            "id": str(uuid4()),
            "model_name": "gpt-4.1",
            "model_slug": "gpt-4.1",
            "context_window": 64000,
            "cost_input_per_1k_tokens": "0.123456",
            "cost_output_per_1k_tokens": "0.654321",
            "description": "Descricao vinda da FastAPI.",
            "is_registered": False,
        }
    ]
    service = ProviderModelsService()
    service.client = FakeFastAPIClient(available_response=ApiResponse(status_code=200, data=available_payload))  # type: ignore[assignment]
    service.admin_token = "test-token"

    monkeypatch.setattr(
        "core.services.provider_models_service.get_known_models",
        lambda slug: [
            KnownModel(
                key="gpt-4-1",
                label="GPT-4.1",
                name="GPT-4.1",
                slug="gpt-4-1",
                context_window=128000,
                input_cost_per_1k=Decimal("0.002000"),
                output_cost_per_1k=Decimal("0.008000"),
                description="Descricao local nao deve sobrescrever.",
            )
        ],
    )

    payload = service.get_available_models(provider=provider)
    item = payload["items"][0]

    assert item["context_window"] == 64000
    assert item["input_cost_per_1k"] == Decimal("0.123456")
    assert item["output_cost_per_1k"] == Decimal("0.654321")
    assert item["description"] == "Descricao vinda da FastAPI."
