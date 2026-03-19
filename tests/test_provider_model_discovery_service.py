from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

import app.api.routes.admin_catalog as admin_catalog_route
from app.core.config import get_settings
from app.core.crypto import encrypt_secret
from app.core.exceptions import AppException
from app.db.session import get_operational_session
from app.main import app
from app.models.operational import DjangoAiProvider, DjangoAiProviderCredential, DjangoAiProviderModel
from app.services.auth_service import AuthService
from app.services.provider_model_discovery_service import ProviderModelDiscoveryService

TEST_FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


@pytest.fixture(autouse=True)
def _configure_encryption_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "credentials_encryption_key", TEST_FERNET_KEY)


class FakeSession:
    pass


class FakeProviderRepository:
    def __init__(
        self,
        *,
        provider: DjangoAiProvider | None = None,
        credential: DjangoAiProviderCredential | None = None,
    ) -> None:
        self.provider = provider
        self.credential = credential

    def get_by_id(self, provider_id: UUID) -> DjangoAiProvider | None:
        if self.provider is None:
            return None
        if self.provider.id == provider_id:
            return self.provider
        return None

    def get_active_credential(self, provider_id: UUID) -> DjangoAiProviderCredential | None:
        if self.credential is None:
            return None
        if self.credential.provider_id == provider_id and self.credential.is_active:
            return self.credential
        return None


class FakeProviderModelRepository:
    def __init__(self, *, models: list[DjangoAiProviderModel] | None = None) -> None:
        self.models = models or []

    def list_by_provider(self, provider_id: UUID) -> list[DjangoAiProviderModel]:
        return [item for item in self.models if item.provider_id == provider_id]


def _build_provider(*, slug: str = "openai", is_active: bool = True) -> DjangoAiProvider:
    now = datetime.now(timezone.utc)
    provider = DjangoAiProvider(
        id=uuid4(),
        name=slug.upper(),
        slug=slug,
        description=None,
        is_active=is_active,
    )
    provider.created_at = now
    provider.updated_at = now
    return provider


def _build_credential(*, provider_id: UUID, api_key: str = "sk-test", is_active: bool = True) -> DjangoAiProviderCredential:
    now = datetime.now(timezone.utc)
    credential = DjangoAiProviderCredential(
        id=uuid4(),
        provider_id=provider_id,
        credential_name="main",
        encrypted_api_key=encrypt_secret(api_key),
        config_json={},
        is_active=is_active,
    )
    credential.created_at = now
    credential.updated_at = now
    return credential


def _build_model(*, provider_id: UUID, model_slug: str) -> DjangoAiProviderModel:
    now = datetime.now(timezone.utc)
    model = DjangoAiProviderModel(
        id=uuid4(),
        provider_id=provider_id,
        model_name=model_slug,
        model_slug=model_slug,
        context_limit=8192,
        cost_input_per_1k_tokens=0,
        cost_output_per_1k_tokens=0,
        is_active=True,
    )
    model.created_at = now
    model.updated_at = now
    return model


def test_discovery_returns_normalized_models_and_marks_registered(monkeypatch) -> None:
    provider = _build_provider(slug="openai", is_active=True)
    credential = _build_credential(provider_id=provider.id, api_key="sk-live-abc")
    local_model = _build_model(provider_id=provider.id, model_slug="gpt-4o-mini")

    service = ProviderModelDiscoveryService(FakeSession())  # type: ignore[arg-type]
    service.providers = FakeProviderRepository(provider=provider, credential=credential)  # type: ignore[assignment]
    service.models = FakeProviderModelRepository(models=[local_model])  # type: ignore[assignment]

    called: dict[str, str] = {}

    def fake_fetch(self, *, api_key: str, config_json: dict):  # type: ignore[no-untyped-def]
        called["api_key"] = api_key
        return [
            {"id": "gpt-4o-mini", "owned_by": "openai"},
            {"id": "gpt-4.1", "owned_by": "openai"},
        ]

    monkeypatch.setattr(
        ProviderModelDiscoveryService,
        "_fetch_openai_available_models",
        fake_fetch,
    )

    payload = service.list_available_models(provider_id=provider.id)

    assert called["api_key"] == "sk-live-abc"
    assert [item["model_slug"] for item in payload] == ["gpt-4.1", "gpt-4o-mini"]
    assert payload[0]["is_registered"] is False
    assert payload[1]["is_registered"] is True
    assert all("sk-live-abc" not in str(item) for item in payload)


def test_discovery_fails_for_inactive_provider() -> None:
    provider = _build_provider(slug="openai", is_active=False)
    credential = _build_credential(provider_id=provider.id)
    service = ProviderModelDiscoveryService(FakeSession())  # type: ignore[arg-type]
    service.providers = FakeProviderRepository(provider=provider, credential=credential)  # type: ignore[assignment]
    service.models = FakeProviderModelRepository()  # type: ignore[assignment]

    with pytest.raises(AppException) as exc:
        service.list_available_models(provider_id=provider.id)
    assert exc.value.payload.code == "provider_inactive"


def test_discovery_fails_without_active_credential() -> None:
    provider = _build_provider(slug="openai", is_active=True)
    service = ProviderModelDiscoveryService(FakeSession())  # type: ignore[arg-type]
    service.providers = FakeProviderRepository(provider=provider, credential=None)  # type: ignore[assignment]
    service.models = FakeProviderModelRepository()  # type: ignore[assignment]

    with pytest.raises(AppException) as exc:
        service.list_available_models(provider_id=provider.id)
    assert exc.value.payload.code == "provider_credential_not_found"


def test_discovery_supports_anthropic_and_normalizes_capabilities(monkeypatch) -> None:
    provider = _build_provider(slug="claude", is_active=True)
    credential = _build_credential(provider_id=provider.id, api_key="sk-ant-abc")
    local_model = _build_model(provider_id=provider.id, model_slug="claude-3-5-haiku-latest")
    service = ProviderModelDiscoveryService(FakeSession())  # type: ignore[arg-type]
    service.providers = FakeProviderRepository(provider=provider, credential=credential)  # type: ignore[assignment]
    service.models = FakeProviderModelRepository(models=[local_model])  # type: ignore[assignment]

    called: dict[str, str] = {}

    def fake_fetch(self, *, api_key: str, config_json: dict):  # type: ignore[no-untyped-def]
        called["api_key"] = api_key
        return [
            {
                "id": "claude-3-7-sonnet-latest",
                "display_name": "Claude 3.7 Sonnet",
                "capabilities": {"vision": True, "thinking": True},
                "max_context_tokens": 200000,
            },
            {
                "id": "claude-3-5-haiku-latest",
                "display_name": "Claude 3.5 Haiku",
            },
        ]

    monkeypatch.setattr(
        ProviderModelDiscoveryService,
        "_fetch_anthropic_available_models",
        fake_fetch,
    )

    payload = service.list_available_models(provider_id=provider.id)
    assert called["api_key"] == "sk-ant-abc"
    assert [item["model_slug"] for item in payload] == [
        "claude-3-5-haiku-latest",
        "claude-3-7-sonnet-latest",
    ]
    assert payload[0]["is_registered"] is True
    assert payload[1]["is_registered"] is False
    assert payload[1]["supports_vision"] is True
    assert payload[1]["supports_thinking"] is True
    assert payload[1]["context_limit"] == 200000
    assert payload[1]["provider_slug"] == "claude"
    assert payload[1]["description"] == "Modelo descoberto via API nativa Anthropic."


def test_discovery_fails_for_provider_not_supported() -> None:
    provider = _build_provider(slug="gemini", is_active=True)
    credential = _build_credential(provider_id=provider.id)
    service = ProviderModelDiscoveryService(FakeSession())  # type: ignore[arg-type]
    service.providers = FakeProviderRepository(provider=provider, credential=credential)  # type: ignore[assignment]
    service.models = FakeProviderModelRepository()  # type: ignore[assignment]

    with pytest.raises(AppException) as exc:
        service.list_available_models(provider_id=provider.id)
    assert exc.value.payload.code == "provider_discovery_not_supported"


def test_openapi_contains_available_models_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json().get("paths", {})
    assert "/api/v1/admin/providers/{provider_id}/available-models" in paths


def test_available_models_route_returns_payload(monkeypatch) -> None:
    provider_id = uuid4()

    class FakeDiscoveryService:
        def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
            self.session = session

        def list_available_models(self, *, provider_id: UUID):  # type: ignore[override]
            return [
                {
                    "provider_id": provider_id,
                    "provider_slug": "openai",
                    "provider_model_id": "gpt-4o-mini",
                    "model_name": "gpt-4o-mini",
                    "model_slug": "gpt-4o-mini",
                    "context_limit": None,
                    "cost_input_per_1k_tokens": None,
                    "cost_output_per_1k_tokens": None,
                    "description": "Modelo descoberto via API do provider.",
                    "is_registered": True,
                }
            ]

    def override_operational_session():  # type: ignore[no-untyped-def]
        yield object()

    def fake_get_user_from_admin_jwt(self, token: str):  # type: ignore[no-untyped-def]
        return SimpleNamespace(id=uuid4(), role=SimpleNamespace(name="super_admin"), is_active=True)

    monkeypatch.setattr(admin_catalog_route, "ProviderModelDiscoveryService", FakeDiscoveryService)
    monkeypatch.setattr(AuthService, "get_user_from_admin_jwt", fake_get_user_from_admin_jwt)
    app.dependency_overrides[get_operational_session] = override_operational_session

    try:
        client = TestClient(app)
        response = client.get(
            f"/api/v1/admin/providers/{provider_id}/available-models",
            headers={"Authorization": "Bearer test-admin-token"},
        )
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list) and len(body) == 1
        assert body[0]["model_slug"] == "gpt-4o-mini"
        assert body[0]["is_registered"] is True
    finally:
        app.dependency_overrides.clear()
