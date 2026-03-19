import os
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.services.api_client import ApiResponse
from core.services.provider_models_service import ProviderModelsService, ProviderModelsServiceError
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


class FakeDeleteFastAPIClient:
    def __init__(self, response: ApiResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def get_admin_headers(self):  # type: ignore[no-untyped-def]
        return {"Authorization": "Bearer test-token"}

    def request_json(self, **kwargs):  # type: ignore[no-untyped-def]
        method = str(kwargs.get("method") or "").upper()
        path = str(kwargs.get("path") or "")
        self.calls.append((method, path))
        return self.response


class FakeRemoteModelEntryClient:
    def __init__(self, responses: dict[tuple[str, str], ApiResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def get_admin_headers(self):  # type: ignore[no-untyped-def]
        return {"Authorization": "Bearer test-token"}

    def request_json(self, **kwargs):  # type: ignore[no-untyped-def]
        method = str(kwargs.get("method") or "").upper()
        path = str(kwargs.get("path") or "")
        self.calls.append((method, path))
        key = (method, path)
        if key not in self.responses:
            raise AssertionError(f"Unexpected request: {key}")
        return self.responses[key]


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


def test_delete_remote_model_accepts_success() -> None:
    service = ProviderModelsService()
    model_id = uuid4()
    client = FakeDeleteFastAPIClient(ApiResponse(status_code=204, data={}))
    service.client = client  # type: ignore[assignment]
    service.admin_token = "test-token"

    service.delete_remote_model(fastapi_model_id=model_id)

    assert client.calls == [("DELETE", f"/api/v1/admin/models/{model_id}")]


def test_delete_remote_model_ignores_remote_not_found() -> None:
    service = ProviderModelsService()
    model_id = uuid4()
    client = FakeDeleteFastAPIClient(
        ApiResponse(
            status_code=404,
            data={"error": {"code": "provider_model_not_found", "message": "not found"}},
            error="not found",
        )
    )
    service.client = client  # type: ignore[assignment]
    service.admin_token = "test-token"

    service.delete_remote_model(fastapi_model_id=model_id)

    assert client.calls == [("DELETE", f"/api/v1/admin/models/{model_id}")]


def test_delete_remote_model_raises_for_other_errors() -> None:
    service = ProviderModelsService()
    model_id = uuid4()
    client = FakeDeleteFastAPIClient(
        ApiResponse(
            status_code=422,
            data={"error": {"code": "provider_model_in_use", "message": "in use"}},
            error="in use",
        )
    )
    service.client = client  # type: ignore[assignment]
    service.admin_token = "test-token"

    try:
        service.delete_remote_model(fastapi_model_id=model_id)
    except ProviderModelsServiceError as exc:
        assert "in use" in str(exc).lower()
    else:
        raise AssertionError("Expected ProviderModelsServiceError")


def test_delete_remote_model_entry_removes_by_slug_when_fastapi_id_missing() -> None:
    service = ProviderModelsService()
    provider = _provider(slug="openai")
    remote_id = uuid4()
    responses = {
        (
            "GET",
            f"/api/v1/admin/providers/{provider.fastapi_provider_id}/models",
        ): ApiResponse(
            status_code=200,
            data=[
                {
                    "id": str(remote_id),
                    "provider_id": str(provider.fastapi_provider_id),
                    "model_name": "gpt-4o-mini",
                    "model_slug": "gpt-4o-mini",
                    "context_limit": 128000,
                    "cost_input_per_1k_tokens": "0.000150",
                    "cost_output_per_1k_tokens": "0.000600",
                    "is_active": True,
                }
            ],
        ),
        ("DELETE", f"/api/v1/admin/models/{remote_id}"): ApiResponse(status_code=204, data={}),
    }
    client = FakeRemoteModelEntryClient(responses)
    service.client = client  # type: ignore[assignment]
    service.admin_token = "test-token"

    deleted_count = service.delete_remote_model_entry(
        provider=provider,
        model_slug="gpt-4o-mini",
        fastapi_model_id=None,
    )

    assert deleted_count == 1
    assert ("DELETE", f"/api/v1/admin/models/{remote_id}") in client.calls


def test_delete_remote_model_entry_deletes_residual_when_fastapi_id_wrong() -> None:
    service = ProviderModelsService()
    provider = _provider(slug="openai")
    wrong_id = uuid4()
    real_id = uuid4()
    responses = {
        ("DELETE", f"/api/v1/admin/models/{wrong_id}"): ApiResponse(
            status_code=404,
            data={"error": {"code": "provider_model_not_found", "message": "not found"}},
            error="not found",
        ),
        (
            "GET",
            f"/api/v1/admin/providers/{provider.fastapi_provider_id}/models",
        ): ApiResponse(
            status_code=200,
            data=[
                {
                    "id": str(real_id),
                    "provider_id": str(provider.fastapi_provider_id),
                    "model_name": "gpt-4o-mini",
                    "model_slug": "gpt-4o-mini",
                    "context_limit": 128000,
                    "cost_input_per_1k_tokens": "0.000150",
                    "cost_output_per_1k_tokens": "0.000600",
                    "is_active": True,
                }
            ],
        ),
        ("DELETE", f"/api/v1/admin/models/{real_id}"): ApiResponse(status_code=204, data={}),
    }
    client = FakeRemoteModelEntryClient(responses)
    service.client = client  # type: ignore[assignment]
    service.admin_token = "test-token"

    deleted_count = service.delete_remote_model_entry(
        provider=provider,
        model_slug="gpt-4o-mini",
        fastapi_model_id=wrong_id,
    )

    assert deleted_count == 1
    assert ("DELETE", f"/api/v1/admin/models/{wrong_id}") in client.calls
    assert ("DELETE", f"/api/v1/admin/models/{real_id}") in client.calls
