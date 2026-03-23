from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.jwt import create_admin_jwt
from app.core.security import hash_token
from app.models.operational import DjangoAiApiToken, DjangoAiApiTokenPermission, DjangoAiIntegrationToken
from app.services.auth_service import AdminLoginResult, AuthService
from app.services.token_service import ApiTokenService, check_token_permission
from app.main import app


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.refresh_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def refresh(self, _: object) -> None:
        self.refresh_calls += 1


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list[object] = []

    def add(self, audit_log: object) -> object:
        self.events.append(audit_log)
        return audit_log


class FakeTokenRepository:
    def __init__(self) -> None:
        self.tokens: dict[str, DjangoAiApiToken] = {}
        self.permissions: dict[str, list[DjangoAiApiTokenPermission]] = {}
        self.logs: list[object] = []

    def add(self, token: DjangoAiApiToken) -> DjangoAiApiToken:
        if token.id is None:
            token.id = uuid4()
        now = datetime.now(timezone.utc)
        token.created_at = now
        token.updated_at = now
        self.tokens[str(token.id)] = token
        return token

    def add_permission(self, permission: DjangoAiApiTokenPermission) -> DjangoAiApiTokenPermission:
        self.permissions.setdefault(str(permission.token_id), []).append(permission)
        return permission

    def list_all(self) -> list[DjangoAiApiToken]:
        return list(self.tokens.values())

    def get_by_hash(self, token_hash: str) -> DjangoAiApiToken | None:
        for token in self.tokens.values():
            if token.token_hash == token_hash:
                return token
        return None

    def get_permissions(self, token_id) -> list[DjangoAiApiTokenPermission]:  # type: ignore[no-untyped-def]
        return self.permissions.get(str(token_id), [])

    def get_by_id(self, token_id) -> DjangoAiApiToken | None:  # type: ignore[no-untyped-def]
        return self.tokens.get(str(token_id))

    def revoke(self, token_id) -> DjangoAiApiToken | None:  # type: ignore[no-untyped-def]
        token = self.tokens.get(str(token_id))
        if token is None:
            return None
        token.is_active = False
        return token

    def delete(self, token_id) -> bool:  # type: ignore[no-untyped-def]
        return self.tokens.pop(str(token_id), None) is not None

    def add_log(self, log: object) -> object:
        self.logs.append(log)
        return log


def test_admin_login_endpoint_returns_jwt(monkeypatch) -> None:
    user_id = uuid4()
    role = SimpleNamespace(name="super_admin")
    fake_user = SimpleNamespace(id=user_id, name="Admin", email="admin@nef.local", role=role, is_active=True)

    def fake_login_admin(self, *, email: str, password: str, ip_address: str | None = None):  # type: ignore[no-untyped-def]
        token, expires_at = create_admin_jwt(user_id=str(user_id), role=role.name)
        return AdminLoginResult(user=fake_user, access_token=token, expires_at=expires_at)

    monkeypatch.setattr(AuthService, "login_admin", fake_login_admin)
    client = TestClient(app)

    response = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "admin@nef.local", "password": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and len(body["access_token"]) > 20


def test_api_token_generation_stores_hash_only() -> None:
    session = FakeSession()
    service = ApiTokenService(session)  # type: ignore[arg-type]
    fake_repo = FakeTokenRepository()
    service.tokens = fake_repo  # type: ignore[assignment]
    service.audit = FakeAuditRepository()  # type: ignore[assignment]

    automation_id = uuid4()
    token_model, plaintext_token = service.create_token(
        name="integration-token",
        created_by_user_id=uuid4(),
        expires_at=None,
        permissions=[
            {
                "automation_id": automation_id,
                "provider_id": None,
                "allow_execution": True,
                "allow_file_upload": False,
            }
        ],
    )

    settings = get_settings()
    assert plaintext_token.startswith(f"{settings.api_token_prefix}_")
    assert token_model.token_hash != plaintext_token
    assert len(fake_repo.get_permissions(token_model.id)) == 1
    assert session.commit_calls == 1


def test_api_token_validation_and_permission_check() -> None:
    session = FakeSession()
    service = ApiTokenService(session)  # type: ignore[arg-type]
    fake_repo = FakeTokenRepository()
    service.tokens = fake_repo  # type: ignore[assignment]
    service.audit = FakeAuditRepository()  # type: ignore[assignment]

    raw_token = "ia_live_testtoken"
    token_model = DjangoAiApiToken(
        name="token",
        token_hash=hash_token(raw_token),
        is_active=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        created_by_user_id=uuid4(),
    )
    fake_repo.add(token_model)

    permission = DjangoAiApiTokenPermission(
        token_id=token_model.id,
        automation_id=uuid4(),
        provider_id=None,
        allow_execution=True,
        allow_file_upload=False,
    )
    fake_repo.add_permission(permission)

    validation = service.validate_token(raw_token)
    assert validation.token.id == token_model.id
    assert check_token_permission(
        permissions=validation.permissions,
        operation="execution",
        automation_id=permission.automation_id,
    )


def test_api_token_revocation() -> None:
    session = FakeSession()
    service = ApiTokenService(session)  # type: ignore[arg-type]
    fake_repo = FakeTokenRepository()
    service.tokens = fake_repo  # type: ignore[assignment]
    service.audit = FakeAuditRepository()  # type: ignore[assignment]

    token_model = DjangoAiApiToken(
        name="revokable",
        token_hash="hash",
        is_active=True,
        expires_at=None,
        created_by_user_id=uuid4(),
    )
    fake_repo.add(token_model)

    revoked = service.revoke_token(token_id=token_model.id, actor_user_id=uuid4())
    assert revoked.is_active is False
    assert session.commit_calls == 1


def test_api_token_validation_normalizes_wrapped_values() -> None:
    session = FakeSession()
    service = ApiTokenService(session)  # type: ignore[arg-type]
    fake_repo = FakeTokenRepository()
    service.tokens = fake_repo  # type: ignore[assignment]
    service.audit = FakeAuditRepository()  # type: ignore[assignment]

    raw_token = "ia_live_testtoken"
    token_model = DjangoAiApiToken(
        name="token",
        token_hash=hash_token(raw_token),
        is_active=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        created_by_user_id=uuid4(),
    )
    fake_repo.add(token_model)

    validation_with_quotes = service.validate_token(f'"{raw_token}"')
    assert validation_with_quotes.token.id == token_model.id

    validation_with_bearer = service.validate_token(f"Bearer {raw_token}")
    assert validation_with_bearer.token.id == token_model.id


def test_api_token_validation_accepts_integration_tokens_with_ia_int_prefix(monkeypatch) -> None:
    session = FakeSession()
    service = ApiTokenService(session)  # type: ignore[arg-type]
    fake_repo = FakeTokenRepository()
    service.tokens = fake_repo  # type: ignore[assignment]
    service.audit = FakeAuditRepository()  # type: ignore[assignment]

    raw_token = "ia_int_only_integration_token"
    token_hash = hash_token(raw_token)
    integration_token = DjangoAiIntegrationToken(
        name="django-integration",
        token_hash=token_hash,
        is_active=True,
        created_by_user_id=uuid4(),
    )
    integration_token.id = uuid4()

    monkeypatch.setattr(
        "app.services.token_service.IntegrationTokenRepository.get_by_hash",
        lambda self, lookup_hash: integration_token if lookup_hash == token_hash else None,
    )

    validation = service.validate_token(raw_token)
    assert validation.token.id == integration_token.id
    mirrored = fake_repo.get_by_hash(token_hash)
    assert mirrored is not None
    assert mirrored.name.startswith("integration::")
    assert session.commit_calls == 1


def test_api_token_validation_fallbacks_to_api_tokens_when_ia_int_not_found_on_integration(monkeypatch) -> None:
    session = FakeSession()
    service = ApiTokenService(session)  # type: ignore[arg-type]
    fake_repo = FakeTokenRepository()
    service.tokens = fake_repo  # type: ignore[assignment]
    service.audit = FakeAuditRepository()  # type: ignore[assignment]

    raw_token = "ia_int_api_token"
    token_model = DjangoAiApiToken(
        name="token",
        token_hash=hash_token(raw_token),
        is_active=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        created_by_user_id=uuid4(),
    )
    fake_repo.add(token_model)

    monkeypatch.setattr(
        "app.services.token_service.IntegrationTokenRepository.get_by_hash",
        lambda self, token_hash: None,
    )

    validation = service.validate_token(raw_token)
    assert validation.token.id == token_model.id
