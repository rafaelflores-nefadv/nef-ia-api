from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.core.crypto import encrypt_secret
from app.core.exceptions import AppException
from app.services.provider_service import ProviderService

TEST_FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


class FakeProviderRepository:
    def __init__(self, credential_value: str, *, provider_slug: str = "openai") -> None:
        self.provider = SimpleNamespace(id=uuid4(), slug=provider_slug, is_active=True)
        self.credential = SimpleNamespace(id=uuid4(), encrypted_api_key=credential_value, is_active=True)

    def get_by_slug(self, slug: str):  # type: ignore[no-untyped-def]
        if slug != self.provider.slug:
            return None
        return self.provider

    def get_by_id(self, provider_id):  # type: ignore[no-untyped-def]
        if provider_id != self.provider.id:
            return None
        return self.provider

    def get_active_credential(self, provider_id):  # type: ignore[no-untyped-def]
        if provider_id != self.provider.id:
            return None
        return self.credential


class FakeProviderModelRepository:
    def __init__(self, provider_id, *, model_slug: str = "gpt-5") -> None:  # type: ignore[no-untyped-def]
        self.model = SimpleNamespace(
            id=uuid4(),
            provider_id=provider_id,
            model_slug=model_slug,
            is_active=True,
            cost_input_per_1k_tokens=Decimal("0.01"),
            cost_output_per_1k_tokens=Decimal("0.03"),
        )

    def get_by_slug(self, provider_id, model_slug):  # type: ignore[no-untyped-def]
        if provider_id == self.model.provider_id and model_slug == self.model.model_slug:
            return self.model
        return None

    def get_by_model_slug(self, model_slug):  # type: ignore[no-untyped-def]
        if model_slug == self.model.model_slug:
            return self.model
        return None

    def get_by_id(self, model_id):  # type: ignore[no-untyped-def]
        if model_id == self.model.id:
            return self.model
        return None


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def build(self, *, provider_slug: str, api_key: str, timeout_seconds: int):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "provider_slug": provider_slug,
                "api_key": api_key,
                "timeout_seconds": timeout_seconds,
            }
        )
        return SimpleNamespace()


@pytest.fixture(autouse=True)
def _configure_encryption_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "credentials_encryption_key", TEST_FERNET_KEY)


def _build_service(
    credential_value: str,
    *,
    provider_slug: str = "openai",
    model_slug: str = "gpt-5",
) -> tuple[ProviderService, FakeRegistry]:
    service = ProviderService(SimpleNamespace())  # type: ignore[arg-type]
    fake_providers = FakeProviderRepository(credential_value, provider_slug=provider_slug)
    service.providers = fake_providers  # type: ignore[assignment]
    service.models = FakeProviderModelRepository(
        fake_providers.provider.id,
        model_slug=model_slug,
    )  # type: ignore[assignment]
    fake_registry = FakeRegistry()
    service.registry = fake_registry  # type: ignore[assignment]
    return service, fake_registry


def test_provider_service_decrypts_credential_only_at_use_time() -> None:
    raw_secret = "sk-live-very-secret-1234"
    encrypted = encrypt_secret(raw_secret)
    service, registry = _build_service(encrypted)

    runtime = service.resolve_runtime(provider_slug="openai", model_slug="gpt-5")

    assert runtime.provider.slug == "openai"
    assert runtime.model.model_slug == "gpt-5"
    assert registry.calls and registry.calls[0]["api_key"] == raw_secret


def test_provider_service_rejects_legacy_credential_format() -> None:
    service, _ = _build_service("base64:c2stbGVnYWN5")
    with pytest.raises(AppException) as exc:
        service.resolve_runtime(provider_slug="openai", model_slug="gpt-5")
    assert exc.value.payload.code == "legacy_credential_format"


def test_provider_service_fails_without_encryption_key(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "credentials_encryption_key", None)
    service, _ = _build_service("fernet:gAAAAABlegacy-placeholder")
    with pytest.raises(AppException) as exc:
        service.resolve_runtime(provider_slug="openai", model_slug="gpt-5")
    assert exc.value.payload.code == "credentials_encryption_key_missing"


def test_provider_service_resolves_gemini_alias_to_canonical_provider() -> None:
    raw_secret = "gemini-live-key"
    encrypted = encrypt_secret(raw_secret)
    service, registry = _build_service(
        encrypted,
        provider_slug="gemini",
        model_slug="gemini-2.5-pro",
    )

    runtime = service.resolve_runtime(provider_slug="google-ai", model_slug="gemini-2.5-pro")

    assert runtime.provider.slug == "gemini"
    assert runtime.model.model_slug == "gemini-2.5-pro"
    assert registry.calls
    assert registry.calls[0]["provider_slug"] == "gemini"


def test_provider_service_resolves_runtime_by_uuid_identifiers() -> None:
    raw_secret = "sk-live-provider-id"
    encrypted = encrypt_secret(raw_secret)
    service, registry = _build_service(encrypted)
    provider_id = service.providers.provider.id  # type: ignore[attr-defined]
    model_id = service.models.model.id  # type: ignore[attr-defined]

    runtime = service.resolve_runtime(
        provider_slug=str(provider_id),
        model_slug=str(model_id),
    )

    assert runtime.provider.id == provider_id
    assert runtime.model.id == model_id
    assert registry.calls
