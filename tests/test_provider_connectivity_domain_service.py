from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.core.exceptions import AppException
from app.models.operational import DjangoAiProvider, DjangoAiProviderCredential
from app.services.provider_connectivity_service import ProviderConnectivityService


class FakeSession:
    pass


class FakeProviderRepository:
    def __init__(
        self,
        *,
        provider: DjangoAiProvider | None,
        credential: DjangoAiProviderCredential | None,
    ) -> None:
        self.provider = provider
        self.credential = credential

    def get_by_id(self, provider_id):  # type: ignore[no-untyped-def]
        if self.provider is None:
            return None
        if self.provider.id == provider_id:
            return self.provider
        return None

    def list_credentials(self, provider_id):  # type: ignore[no-untyped-def]
        if self.credential is None:
            return []
        if self.credential.provider_id != provider_id:
            return []
        return [self.credential]

    def get_active_credential(self, provider_id):  # type: ignore[no-untyped-def]
        if self.credential is None:
            return None
        if self.credential.provider_id == provider_id and self.credential.is_active:
            return self.credential
        return None


def _build_provider(*, slug: str, is_active: bool = True) -> DjangoAiProvider:
    provider = DjangoAiProvider(
        id=uuid4(),
        name=slug.upper(),
        slug=slug,
        description=None,
        is_active=is_active,
    )
    now = datetime.now(timezone.utc)
    provider.created_at = now
    provider.updated_at = now
    return provider


def _build_credential(provider_id) -> DjangoAiProviderCredential:  # type: ignore[no-untyped-def]
    credential = DjangoAiProviderCredential(
        id=uuid4(),
        provider_id=provider_id,
        credential_name="main",
        encrypted_api_key="fernet:test",
        config_json={},
        is_active=True,
    )
    now = datetime.now(timezone.utc)
    credential.created_at = now
    credential.updated_at = now
    return credential


def test_connectivity_supports_claude_success() -> None:
    provider = _build_provider(slug="claude")
    credential = _build_credential(provider.id)

    service = ProviderConnectivityService(FakeSession())  # type: ignore[arg-type]
    service.providers = FakeProviderRepository(provider=provider, credential=credential)  # type: ignore[assignment]
    service.discovery = SimpleNamespace(  # type: ignore[assignment]
        _decrypt_credential_or_422=lambda credential: "sk-ant-live",  # noqa: ARG005
        fetch_raw_models=lambda **kwargs: ("anthropic", [{"id": "claude-3-7-sonnet-latest"}]),  # noqa: ARG005
    )

    payload = service.test_provider_connectivity(provider_id=provider.id)
    assert payload["ok"] is True
    assert payload["status"] == "connected"
    assert payload["provider_slug"] == "claude"
    assert payload["checks"][-1]["ok"] is True


def test_connectivity_maps_invalid_api_key_for_anthropic() -> None:
    provider = _build_provider(slug="anthropic")
    credential = _build_credential(provider.id)

    def raise_invalid_key(**kwargs):  # type: ignore[no-untyped-def]
        raise AppException(
            "authentication_error",
            status_code=502,
            code="provider_http_error",
            details={"provider": "anthropic", "status_code": 401},
        )

    service = ProviderConnectivityService(FakeSession())  # type: ignore[arg-type]
    service.providers = FakeProviderRepository(provider=provider, credential=credential)  # type: ignore[assignment]
    service.discovery = SimpleNamespace(  # type: ignore[assignment]
        _decrypt_credential_or_422=lambda credential: "sk-ant-live",  # noqa: ARG005
        fetch_raw_models=raise_invalid_key,
    )

    payload = service.test_provider_connectivity(provider_id=provider.id)
    assert payload["ok"] is False
    assert payload["status"] == "api_key_invalid"
    assert payload["error_code"] == "provider_http_error"
    assert payload["checks"][-1]["http_status"] == 401


def test_connectivity_maps_timeout_and_network_errors() -> None:
    provider = _build_provider(slug="anthropic")
    credential = _build_credential(provider.id)

    timeout_service = ProviderConnectivityService(FakeSession())  # type: ignore[arg-type]
    timeout_service.providers = FakeProviderRepository(provider=provider, credential=credential)  # type: ignore[assignment]
    timeout_service.discovery = SimpleNamespace(  # type: ignore[assignment]
        _decrypt_credential_or_422=lambda credential: "sk-ant-live",  # noqa: ARG005
        fetch_raw_models=lambda **kwargs: (_ for _ in ()).throw(  # noqa: ARG005
            AppException(
                "timeout",
                status_code=504,
                code="provider_timeout",
                details={"provider": "anthropic"},
            )
        ),
    )
    timeout_payload = timeout_service.test_provider_connectivity(provider_id=provider.id)
    assert timeout_payload["status"] == "provider_timeout"

    network_service = ProviderConnectivityService(FakeSession())  # type: ignore[arg-type]
    network_service.providers = FakeProviderRepository(provider=provider, credential=credential)  # type: ignore[assignment]
    network_service.discovery = SimpleNamespace(  # type: ignore[assignment]
        _decrypt_credential_or_422=lambda credential: "sk-ant-live",  # noqa: ARG005
        fetch_raw_models=lambda **kwargs: (_ for _ in ()).throw(  # noqa: ARG005
            AppException(
                "network",
                status_code=502,
                code="provider_network_error",
                details={"provider": "anthropic"},
            )
        ),
    )
    network_payload = network_service.test_provider_connectivity(provider_id=provider.id)
    assert network_payload["status"] == "provider_network_error"


def test_connectivity_rejects_unsupported_provider() -> None:
    provider = _build_provider(slug="gemini")
    credential = _build_credential(provider.id)
    service = ProviderConnectivityService(FakeSession())  # type: ignore[arg-type]
    service.providers = FakeProviderRepository(provider=provider, credential=credential)  # type: ignore[assignment]
    service.discovery = SimpleNamespace(  # type: ignore[assignment]
        _decrypt_credential_or_422=lambda credential: "sk-any",  # noqa: ARG005
        fetch_raw_models=lambda **kwargs: ("", []),  # noqa: ARG005
    )

    payload = service.test_provider_connectivity(provider_id=provider.id)
    assert payload["ok"] is False
    assert payload["status"] == "provider_not_supported"
    assert payload["error_code"] == "provider_discovery_not_supported"
