from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import app.api.routes.admin_prompt_tests as admin_prompt_tests_route
from app.api.dependencies.security import get_current_admin_user
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.main import app


def _override_admin_dependencies() -> None:
    def override_current_admin_user():  # type: ignore[no-untyped-def]
        return SimpleNamespace(id=uuid4())

    def override_operational_session():  # type: ignore[no-untyped-def]
        yield object()

    def override_shared_session():  # type: ignore[no-untyped-def]
        yield object()

    app.dependency_overrides[get_current_admin_user] = override_current_admin_user
    app.dependency_overrides[get_operational_session] = override_operational_session
    app.dependency_overrides[get_shared_session] = override_shared_session


def _patch_admin_auth(monkeypatch) -> dict[str, str]:  # type: ignore[no-untyped-def]
    from app.services.auth_service import AuthService

    def fake_get_user_from_admin_jwt(self, token: str):  # type: ignore[no-untyped-def]
        assert token == "admin-jwt-test"
        return SimpleNamespace(id=uuid4(), is_active=True)

    monkeypatch.setattr(AuthService, "get_user_from_admin_jwt", fake_get_user_from_admin_jwt)
    return {"Authorization": "Bearer admin-jwt-test"}


def test_copy_prompt_test_automation_to_official_route_uses_external_catalog_flow(monkeypatch) -> None:
    _override_admin_dependencies()
    headers = _patch_admin_auth(monkeypatch)
    owner_token_id = uuid4()
    provider_id = uuid4()
    model_id = uuid4()
    captured: dict[str, dict] = {}

    class FakeApiTokenRepository:
        def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
            self.session = session

        def get_by_id(self, token_id):  # type: ignore[no-untyped-def]
            return SimpleNamespace(id=token_id, is_active=True)

    class FakeExternalCatalogService:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.kwargs = kwargs

        def create_automation(self, **kwargs):  # type: ignore[no-untyped-def]
            captured["create_automation"] = dict(kwargs)
            return SimpleNamespace(
                id=uuid4(),
                name=kwargs["name"],
            )

        def create_prompt(self, **kwargs):  # type: ignore[no-untyped-def]
            captured["create_prompt"] = dict(kwargs)
            return SimpleNamespace(
                id=uuid4(),
                version=1,
            )

        def delete_automation(self, **kwargs):  # type: ignore[no-untyped-def]
            captured["delete_automation"] = dict(kwargs)
            return None

    monkeypatch.setattr(admin_prompt_tests_route, "ApiTokenRepository", FakeApiTokenRepository)
    monkeypatch.setattr(admin_prompt_tests_route, "ExternalCatalogService", FakeExternalCatalogService)

    payload = {
        "owner_token_id": str(owner_token_id),
        "name": "Automacao de teste",
        "provider_id": str(provider_id),
        "model_id": str(model_id),
        "output_type": "spreadsheet_output",
        "result_parser": "tabular_structured",
        "result_formatter": "spreadsheet_tabular",
        "output_schema": {"columns": ["numero_processo", "categoria"]},
        "is_active": True,
        "prompt_text": "PROMPT VINCULADO",
        "source_test_automation_id": str(uuid4()),
        "source_test_prompt_id": 11,
    }

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/admin/prompt-tests/automations/copy-to-official",
            json=payload,
            headers=headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["owner_token_id"] == str(owner_token_id)
        assert body["automation_name"] == "Automacao de teste"
        assert isinstance(body["automation_id"], str)
        assert isinstance(body["prompt_id"], str)
        assert body["prompt_version"] == 1

        assert captured["create_automation"]["token_id"] == owner_token_id
        assert captured["create_automation"]["provider_id"] == provider_id
        assert captured["create_automation"]["model_id"] == model_id
        assert captured["create_automation"]["output_schema"] == {"columns": ["numero_processo", "categoria"]}
        assert "debug_enabled" not in captured["create_automation"]
        assert captured["create_prompt"]["token_id"] == owner_token_id
    finally:
        app.dependency_overrides.clear()


def test_copy_prompt_test_automation_to_official_route_blocks_empty_prompt(monkeypatch) -> None:
    _override_admin_dependencies()
    headers = _patch_admin_auth(monkeypatch)

    class FakeApiTokenRepository:
        def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
            self.session = session

        def get_by_id(self, token_id):  # type: ignore[no-untyped-def]
            return SimpleNamespace(id=token_id, is_active=True)

    class FakeExternalCatalogService:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.kwargs = kwargs

        def create_automation(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("create_automation should not be called when prompt is empty")

    monkeypatch.setattr(admin_prompt_tests_route, "ApiTokenRepository", FakeApiTokenRepository)
    monkeypatch.setattr(admin_prompt_tests_route, "ExternalCatalogService", FakeExternalCatalogService)

    payload = {
        "owner_token_id": str(uuid4()),
        "name": "Automacao de teste",
        "provider_id": str(uuid4()),
        "model_id": str(uuid4()),
        "is_active": True,
        "prompt_text": "   ",
    }

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/admin/prompt-tests/automations/copy-to-official",
            json=payload,
            headers=headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "copy_test_automation_prompt_missing"
    finally:
        app.dependency_overrides.clear()
