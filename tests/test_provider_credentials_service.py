from types import SimpleNamespace
from uuid import uuid4

from core.services.api_client import ApiResponse
from core.services.provider_credentials_service import (
    ProviderCredentialSyncError,
    ProviderCredentialsService,
)


class FakeClient:
    def __init__(self) -> None:
        self.handler = None

    def get_admin_headers(self):  # type: ignore[no-untyped-def]
        return {"Authorization": "Bearer token"}

    def request_json(self, **kwargs):  # type: ignore[no-untyped-def]
        if self.handler is None:
            raise AssertionError("FakeClient handler was not configured")
        return self.handler(**kwargs)


def _build_credential(*, with_remote_id: bool):  # type: ignore[no-untyped-def]
    provider_id = uuid4()
    provider = SimpleNamespace(fastapi_provider_id=provider_id)
    return SimpleNamespace(
        provider=provider,
        provider_id=1,
        name="Credencial principal",
        api_key="sk-test-123",
        config_json={"timeout_seconds": 30},
        is_active=True,
        fastapi_credential_id=uuid4() if with_remote_id else None,
    )


def test_sync_credential_creates_remote_when_missing_id() -> None:
    fake_client = FakeClient()
    service = ProviderCredentialsService(client=fake_client)  # type: ignore[arg-type]
    credential = _build_credential(with_remote_id=False)
    remote_credential_id = uuid4()

    def fake_request_json(**kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["method"] == "POST"
        assert "/credentials" in kwargs["path"]
        return ApiResponse(
            status_code=201,
            data={"id": str(remote_credential_id)},
            error=None,
        )

    fake_client.handler = fake_request_json
    result = service.sync_credential(credential=credential)
    assert result.ok is True
    assert result.operation == "created"
    assert result.remote_credential_id == remote_credential_id


def test_sync_credential_updates_remote_when_id_exists() -> None:
    fake_client = FakeClient()
    service = ProviderCredentialsService(client=fake_client)  # type: ignore[arg-type]
    credential = _build_credential(with_remote_id=True)

    def fake_request_json(**kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["method"] == "PATCH"
        return ApiResponse(status_code=200, data={"id": str(credential.fastapi_credential_id)}, error=None)

    fake_client.handler = fake_request_json
    result = service.sync_credential(credential=credential, previous_provider_id=credential.provider_id)
    assert result.ok is True
    assert result.operation == "updated"
    assert result.remote_credential_id == credential.fastapi_credential_id


def test_sync_status_requires_remote_id() -> None:
    fake_client = FakeClient()
    service = ProviderCredentialsService(client=fake_client)  # type: ignore[arg-type]
    credential = _build_credential(with_remote_id=False)

    try:
        service.sync_credential_status(credential=credential, target_active=False)
    except ProviderCredentialSyncError as exc:
        assert exc.code == "credential_not_synced"
    else:
        raise AssertionError("Expected ProviderCredentialSyncError for missing remote credential id")
