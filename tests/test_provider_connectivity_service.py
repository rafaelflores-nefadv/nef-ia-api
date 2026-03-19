from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

import app.api.routes.admin_catalog as admin_catalog_route
from app.db.session import get_operational_session
from app.main import app
from app.services.auth_service import AuthService


def test_openapi_contains_provider_connectivity_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json().get("paths", {})
    assert "/api/v1/admin/providers/{provider_id}/connectivity-test" in paths


def test_provider_connectivity_route_returns_structured_payload(monkeypatch) -> None:
    provider_id = uuid4()

    class FakeConnectivityService:
        def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
            self.session = session

        def test_provider_connectivity(self, *, provider_id: UUID):  # type: ignore[override]
            return {
                "ok": False,
                "status": "api_key_invalid",
                "status_label": "API key invalida",
                "message": "Provider rejeitou autenticacao.",
                "provider_id": provider_id,
                "provider_slug": "openai",
                "checks": [
                    {
                        "name": "provider_connectivity",
                        "ok": False,
                        "message": "Provider rejeitou autenticacao.",
                        "code": "provider_http_error",
                        "http_status": 401,
                    }
                ],
            }

    def override_operational_session():  # type: ignore[no-untyped-def]
        yield object()

    def fake_get_user_from_admin_jwt(self, token: str):  # type: ignore[no-untyped-def]
        return SimpleNamespace(id=uuid4(), role=SimpleNamespace(name="super_admin"), is_active=True)

    monkeypatch.setattr(admin_catalog_route, "ProviderConnectivityService", FakeConnectivityService)
    monkeypatch.setattr(AuthService, "get_user_from_admin_jwt", fake_get_user_from_admin_jwt)
    app.dependency_overrides[get_operational_session] = override_operational_session

    try:
        client = TestClient(app)
        response = client.post(
            f"/api/v1/admin/providers/{provider_id}/connectivity-test",
            headers={"Authorization": "Bearer test-admin-token"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert payload["status"] == "api_key_invalid"
        assert payload["provider_slug"] == "openai"
        assert payload["checks"][0]["http_status"] == 401
    finally:
        app.dependency_overrides.clear()
