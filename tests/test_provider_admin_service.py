from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes.admin_catalog import _credential_to_response
from app.core.config import get_settings
from app.core.crypto import decrypt_secret
from app.core.exceptions import AppException
from app.main import app
from app.models.operational import DjangoAiProvider, DjangoAiProviderCredential, DjangoAiProviderModel
from app.services.provider_admin_service import ProviderAdminService

TEST_FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


@pytest.fixture(autouse=True)
def _configure_encryption_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "credentials_encryption_key", TEST_FERNET_KEY)


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.refresh_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def refresh(self, _: object) -> None:
        self.refresh_calls += 1


class FakeProviderRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, DjangoAiProvider] = {}

    def add(self, provider: DjangoAiProvider) -> DjangoAiProvider:
        if provider.id is None:
            provider.id = uuid4()
        now = datetime.now(timezone.utc)
        provider.created_at = provider.created_at or now
        provider.updated_at = now
        self.items[provider.id] = provider
        return provider

    def list_all(self) -> list[DjangoAiProvider]:
        return list(self.items.values())

    def get_by_id(self, provider_id: UUID) -> DjangoAiProvider | None:
        return self.items.get(provider_id)

    def get_by_slug(self, slug: str) -> DjangoAiProvider | None:
        for item in self.items.values():
            if item.slug == slug:
                return item
        return None


class FakeProviderModelRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, DjangoAiProviderModel] = {}

    def add(self, model: DjangoAiProviderModel) -> DjangoAiProviderModel:
        if model.id is None:
            model.id = uuid4()
        now = datetime.now(timezone.utc)
        model.created_at = model.created_at or now
        model.updated_at = now
        self.items[model.id] = model
        return model

    def get_by_id(self, model_id: UUID) -> DjangoAiProviderModel | None:
        return self.items.get(model_id)

    def list_by_provider(self, provider_id: UUID) -> list[DjangoAiProviderModel]:
        return [item for item in self.items.values() if item.provider_id == provider_id]

    def get_by_slug(self, provider_id: UUID, model_slug: str) -> DjangoAiProviderModel | None:
        for item in self.items.values():
            if item.provider_id == provider_id and item.model_slug == model_slug:
                return item
        return None

    def get_by_model_slug(self, model_slug: str) -> DjangoAiProviderModel | None:
        for item in self.items.values():
            if item.model_slug == model_slug:
                return item
        return None


class FakeProviderCredentialRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, DjangoAiProviderCredential] = {}

    def add(self, credential: DjangoAiProviderCredential) -> DjangoAiProviderCredential:
        if credential.id is None:
            credential.id = uuid4()
        now = datetime.now(timezone.utc)
        credential.created_at = credential.created_at or now
        credential.updated_at = now
        self.items[credential.id] = credential
        return credential

    def get_by_id(self, credential_id: UUID) -> DjangoAiProviderCredential | None:
        return self.items.get(credential_id)

    def list_by_provider(self, provider_id: UUID) -> list[DjangoAiProviderCredential]:
        return [item for item in self.items.values() if item.provider_id == provider_id]

    def get_by_name(self, *, provider_id: UUID, credential_name: str) -> DjangoAiProviderCredential | None:
        for item in self.items.values():
            if item.provider_id == provider_id and item.credential_name == credential_name:
                return item
        return None


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list[object] = []

    def add(self, event: object) -> object:
        self.events.append(event)
        return event


def _build_service() -> ProviderAdminService:
    session = FakeSession()
    service = ProviderAdminService(session)  # type: ignore[arg-type]
    service.providers = FakeProviderRepository()  # type: ignore[assignment]
    service.models = FakeProviderModelRepository()  # type: ignore[assignment]
    service.credentials = FakeProviderCredentialRepository()  # type: ignore[assignment]
    service.audit = FakeAuditRepository()  # type: ignore[assignment]
    return service


def test_create_generic_provider() -> None:
    service = _build_service()
    provider = service.create_provider(
        name="Google Gemini",
        slug="gemini",
        description="Provider generico",
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    assert provider.slug == "gemini"
    assert provider.is_active is True


def test_update_and_activate_deactivate_provider() -> None:
    service = _build_service()
    provider = service.create_provider(
        name="OpenAI",
        slug="openai",
        description=None,
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    updated = service.update_provider(
        provider_id=provider.id,
        name="OpenAI Inc.",
        slug=None,
        description="Atualizado",
        is_active=None,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    assert updated.name == "OpenAI Inc."

    deactivated = service.deactivate_provider(provider_id=provider.id, actor_user_id=uuid4(), ip_address=None)
    assert deactivated.is_active is False

    activated = service.activate_provider(provider_id=provider.id, actor_user_id=uuid4(), ip_address=None)
    assert activated.is_active is True


def test_create_model_for_provider() -> None:
    service = _build_service()
    provider = service.create_provider(
        name="Anthropic",
        slug="anthropic",
        description=None,
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    model = service.create_model(
        provider_id=provider.id,
        model_name="Claude Sonnet",
        model_slug="claude-sonnet",
        context_limit=200000,
        cost_input_per_1k_tokens=Decimal("0.003"),
        cost_output_per_1k_tokens=Decimal("0.015"),
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    assert model.provider_id == provider.id
    assert model.model_slug == "claude-sonnet"


def test_activate_model_fails_when_provider_inactive() -> None:
    service = _build_service()
    provider = service.create_provider(
        name="OpenAI",
        slug="openai",
        description=None,
        is_active=False,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    model = service.create_model(
        provider_id=provider.id,
        model_name="GPT 5",
        model_slug="gpt-5",
        context_limit=128000,
        cost_input_per_1k_tokens=Decimal("0.01"),
        cost_output_per_1k_tokens=Decimal("0.03"),
        is_active=False,
        actor_user_id=uuid4(),
        ip_address=None,
    )

    try:
        service.activate_model(model_id=model.id, actor_user_id=uuid4(), ip_address=None)
    except AppException as exc:
        assert exc.payload.code == "provider_inactive"
    else:
        raise AssertionError("Expected provider_inactive error.")


def test_create_credential_encrypts_secret_and_response_masks_it() -> None:
    service = _build_service()
    provider = service.create_provider(
        name="OpenAI",
        slug="openai",
        description=None,
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    raw_secret = "sk-live-123456"
    credential = service.create_credential(
        provider_id=provider.id,
        credential_name="primary",
        api_key=raw_secret,
        config_json={"region": "us"},
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    assert credential.encrypted_api_key != raw_secret
    assert credential.encrypted_api_key.startswith("fernet:")
    assert decrypt_secret(credential.encrypted_api_key) == raw_secret

    response = _credential_to_response(credential)
    payload = response.model_dump()
    assert payload["secret_masked"] != "********"
    assert "****" in payload["secret_masked"]
    assert "encrypted_api_key" not in payload
    assert raw_secret not in str(payload)


def test_create_credential_fails_without_encryption_key(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "credentials_encryption_key", None)
    service = _build_service()
    provider = service.create_provider(
        name="OpenAI",
        slug="openai",
        description=None,
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    with pytest.raises(AppException) as exc:
        service.create_credential(
            provider_id=provider.id,
            credential_name="primary",
            api_key="sk-live-123456",
            config_json={},
            is_active=True,
            actor_user_id=uuid4(),
            ip_address=None,
        )
    assert exc.value.payload.code == "credentials_encryption_key_missing"


def test_legacy_credential_format_is_explicitly_rejected() -> None:
    with pytest.raises(AppException) as exc:
        decrypt_secret("base64:c2stbGVnYWN5")
    assert exc.value.payload.code == "legacy_credential_format"


def test_secret_does_not_appear_in_logs(caplog) -> None:
    service = _build_service()
    provider = service.create_provider(
        name="OpenAI",
        slug="openai",
        description=None,
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    raw_secret = "sk-live-log-check-9999"
    caplog.set_level("INFO")
    service.create_credential(
        provider_id=provider.id,
        credential_name="primary",
        api_key=raw_secret,
        config_json={},
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    assert raw_secret not in caplog.text


def test_catalog_status_returns_operational_view() -> None:
    service = _build_service()
    provider = service.create_provider(
        name="OpenAI",
        slug="openai",
        description=None,
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    service.create_model(
        provider_id=provider.id,
        model_name="GPT 4.1",
        model_slug="gpt-4.1",
        context_limit=128000,
        cost_input_per_1k_tokens=Decimal("0.01"),
        cost_output_per_1k_tokens=Decimal("0.03"),
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    service.create_credential(
        provider_id=provider.id,
        credential_name="main",
        api_key="sk-main",
        config_json={},
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )

    status = service.build_catalog_status()
    assert status["providers"][0]["operational_ready"] is True
    assert status["global_inconsistencies"] == []


def test_catalog_status_handles_multiple_providers_without_hardcode() -> None:
    service = _build_service()
    openai = service.create_provider(
        name="OpenAI",
        slug="openai",
        description=None,
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    gemini = service.create_provider(
        name="Gemini",
        slug="gemini",
        description=None,
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    service.create_model(
        provider_id=openai.id,
        model_name="GPT 5",
        model_slug="gpt-5",
        context_limit=200000,
        cost_input_per_1k_tokens=Decimal("0.01"),
        cost_output_per_1k_tokens=Decimal("0.03"),
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    service.create_credential(
        provider_id=openai.id,
        credential_name="openai-main",
        api_key="sk-openai",
        config_json={},
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    service.create_model(
        provider_id=gemini.id,
        model_name="Gemini 2.5 Pro",
        model_slug="gemini-2.5-pro",
        context_limit=200000,
        cost_input_per_1k_tokens=Decimal("0.012"),
        cost_output_per_1k_tokens=Decimal("0.025"),
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )
    service.create_credential(
        provider_id=gemini.id,
        credential_name="gemini-main",
        api_key="sk-gemini",
        config_json={"project": "ai-core"},
        is_active=True,
        actor_user_id=uuid4(),
        ip_address=None,
    )

    status = service.build_catalog_status()
    slugs = sorted(item["slug"] for item in status["providers"])
    assert slugs == ["gemini", "openai"]
    assert all(item["operational_ready"] for item in status["providers"])


def test_admin_catalog_endpoints_are_protected() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/admin/catalog/status")
    assert response.status_code == 401
