from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import AppException
from app.core.security import hash_token
from app.main import app
from app.models.operational import DjangoAiIntegrationToken
from app.services.auth_service import AuthService
from app.services.integration_token_service import IntegrationTokenService, IntegrationTokenValidationResult


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


class FakeIntegrationTokenRepository:
    def __init__(self) -> None:
        self.tokens: dict[str, DjangoAiIntegrationToken] = {}

    def add(self, token: DjangoAiIntegrationToken) -> DjangoAiIntegrationToken:
        if token.id is None:
            token.id = uuid4()
        now = datetime.now(timezone.utc)
        token.created_at = now
        token.updated_at = now
        self.tokens[str(token.id)] = token
        return token

    def get_by_hash(self, token_hash: str) -> DjangoAiIntegrationToken | None:
        for token in self.tokens.values():
            if token.token_hash == token_hash:
                return token
        return None


def test_integration_token_generation_stores_hash_only() -> None:
    session = FakeSession()
    service = IntegrationTokenService(session)  # type: ignore[arg-type]
    service.tokens = FakeIntegrationTokenRepository()  # type: ignore[assignment]
    service.audit = FakeAuditRepository()  # type: ignore[assignment]

    token_model, plaintext_token = service.create_token(
        name="django-internal",
        created_by_user_id=uuid4(),
    )

    assert plaintext_token.startswith("ia_int_")
    assert token_model.token_hash == hash_token(plaintext_token)
    assert token_model.token_hash != plaintext_token
    assert session.commit_calls == 1


def test_admin_endpoint_accepts_x_integration_token(monkeypatch) -> None:
    user_id = uuid4()
    fake_role = SimpleNamespace(name="super_admin")
    fake_user = SimpleNamespace(id=user_id, name="Django", email="django@local", role=fake_role, is_active=True)
    fake_token = SimpleNamespace(id=uuid4(), name="django-token", created_by_user_id=user_id)

    def fake_validate(self, raw_token: str):  # type: ignore[no-untyped-def]
        assert raw_token == "ia_int_test_token"
        return IntegrationTokenValidationResult(token=fake_token, user=fake_user)

    def fake_touch(self, *, token_id):  # type: ignore[no-untyped-def]
        assert token_id == fake_token.id

    monkeypatch.setattr(IntegrationTokenService, "validate_token", fake_validate)
    monkeypatch.setattr(IntegrationTokenService, "touch_last_used", fake_touch)

    client = TestClient(app)
    response = client.get(
        "/api/v1/admin/me",
        headers={"X-Integration-Token": "ia_int_test_token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user_id)
    assert body["email"] == "django@local"


def test_admin_endpoint_accepts_bearer_integration_token_fallback(monkeypatch) -> None:
    user_id = uuid4()
    fake_role = SimpleNamespace(name="super_admin")
    fake_user = SimpleNamespace(id=user_id, name="Django", email="django@local", role=fake_role, is_active=True)
    fake_token = SimpleNamespace(id=uuid4(), name="django-token", created_by_user_id=user_id)

    def fake_get_user_from_admin_jwt(self, jwt_token: str):  # type: ignore[no-untyped-def]
        raise AppException("Invalid administrative token.", status_code=401, code="invalid_admin_token")

    def fake_validate(self, raw_token: str):  # type: ignore[no-untyped-def]
        assert raw_token == "ia_int_test_token"
        return IntegrationTokenValidationResult(token=fake_token, user=fake_user)

    def fake_touch(self, *, token_id):  # type: ignore[no-untyped-def]
        assert token_id == fake_token.id

    monkeypatch.setattr(AuthService, "get_user_from_admin_jwt", fake_get_user_from_admin_jwt)
    monkeypatch.setattr(IntegrationTokenService, "validate_token", fake_validate)
    monkeypatch.setattr(IntegrationTokenService, "touch_last_used", fake_touch)

    client = TestClient(app)
    response = client.get(
        "/api/v1/admin/me",
        headers={"Authorization": "Bearer ia_int_test_token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user_id)
    assert body["email"] == "django@local"
