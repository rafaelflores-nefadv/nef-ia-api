from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import app.api.routes.external_catalog as external_catalog_route
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.main import app
from app.services.token_service import ApiTokenService


def _auth_headers(monkeypatch):  # type: ignore[no-untyped-def]
    token_id = uuid4()

    def fake_validate_token(self, raw_token: str):  # type: ignore[no-untyped-def]
        assert raw_token == "ia_live_test_external"
        return SimpleNamespace(token=SimpleNamespace(id=token_id), permissions=[])

    def fake_log_usage(self, **kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(ApiTokenService, "validate_token", fake_validate_token)
    monkeypatch.setattr(ApiTokenService, "log_token_usage", fake_log_usage)
    return {"Authorization": "Bearer ia_live_test_external"}


def _override_sessions() -> None:
    def override_shared_session():  # type: ignore[no-untyped-def]
        yield object()

    def override_operational_session():  # type: ignore[no-untyped-def]
        yield object()

    app.dependency_overrides[get_shared_session] = override_shared_session
    app.dependency_overrides[get_operational_session] = override_operational_session


def test_openapi_external_automation_create_schema_is_complete_without_debug() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    payload = response.json()
    post_schema_ref = (
        payload["paths"]["/api/v1/external/automations"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    )
    schema_name = post_schema_ref.rsplit("/", 1)[-1]
    properties = payload["components"]["schemas"][schema_name]["properties"]

    for required_field in (
        "name",
        "provider_id",
        "model_id",
        "credential_id",
        "output_type",
        "result_parser",
        "result_formatter",
        "output_schema",
        "is_active",
    ):
        assert required_field in properties
    assert "debug" not in properties
    assert "debug_enabled" not in properties


def test_external_automation_create_and_update_routes_use_complete_contract(monkeypatch) -> None:
    headers = _auth_headers(monkeypatch)
    _override_sessions()

    provider_id = uuid4()
    model_id = uuid4()
    credential_id = uuid4()
    automation_id = uuid4()

    class FakeExternalCatalogService:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.kwargs = kwargs

        def create_automation(self, **kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                id=automation_id,
                name=kwargs["name"],
                provider_id=kwargs["provider_id"],
                model_id=kwargs["model_id"],
                credential_id=kwargs.get("credential_id"),
                output_type=kwargs.get("output_type"),
                result_parser=kwargs.get("result_parser"),
                result_formatter=kwargs.get("result_formatter"),
                output_schema=kwargs.get("output_schema"),
                is_active=kwargs.get("is_active", True),
            )

        def update_automation(self, **kwargs):  # type: ignore[no-untyped-def]
            changes = kwargs.get("changes") or {}
            return SimpleNamespace(
                id=kwargs["automation_id"],
                name=changes.get("name", "Atualizada"),
                provider_id=changes.get("provider_id", provider_id),
                model_id=changes.get("model_id", model_id),
                credential_id=changes.get("credential_id"),
                output_type=changes.get("output_type"),
                result_parser=changes.get("result_parser"),
                result_formatter=changes.get("result_formatter"),
                output_schema=changes.get("output_schema"),
                is_active=changes.get("is_active", True),
            )

    monkeypatch.setattr(external_catalog_route, "ExternalCatalogService", FakeExternalCatalogService)

    try:
        client = TestClient(app)
        create_payload = {
            "name": "OCR completo",
            "provider_id": str(provider_id),
            "model_id": str(model_id),
            "credential_id": str(credential_id),
            "output_type": "spreadsheet_output",
            "result_parser": "tabular_structured",
            "result_formatter": "spreadsheet_tabular",
            "output_schema": {"columns": ["numero_processo", "categoria"]},
            "is_active": True,
        }
        create_response = client.post("/api/v1/external/automations", json=create_payload, headers=headers)
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["provider_id"] == str(provider_id)
        assert created["model_id"] == str(model_id)
        assert created["credential_id"] == str(credential_id)
        assert created["output_schema"] == {"columns": ["numero_processo", "categoria"]}

        update_response = client.patch(
            f"/api/v1/external/automations/{automation_id}",
            json={
                "name": "OCR atualizado",
                "is_active": False,
                "output_type": "text_output",
                "result_parser": "text_raw",
                "result_formatter": "text_plain",
                "output_schema": {"file_name_template": "execution_{execution_id}.txt"},
            },
            headers=headers,
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["name"] == "OCR atualizado"
        assert updated["is_active"] is False
        assert updated["output_type"] == "text_output"
        assert updated["result_parser"] == "text_raw"
        assert updated["result_formatter"] == "text_plain"
    finally:
        app.dependency_overrides.clear()


def test_external_automation_create_rejects_debug_field(monkeypatch) -> None:
    headers = _auth_headers(monkeypatch)
    _override_sessions()

    class FakeExternalCatalogService:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.kwargs = kwargs

        def create_automation(self, **kwargs):  # type: ignore[no-untyped-def]
            return kwargs

    monkeypatch.setattr(external_catalog_route, "ExternalCatalogService", FakeExternalCatalogService)

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/external/automations",
            json={
                "name": "Com debug indevido",
                "provider_id": str(uuid4()),
                "model_id": str(uuid4()),
                "output_type": "text_output",
                "result_parser": "text_raw",
                "result_formatter": "text_plain",
                "output_schema": {"columns": []},
                "is_active": True,
                "debug_enabled": True,
            },
            headers=headers,
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_external_form_catalog_routes(monkeypatch) -> None:
    headers = _auth_headers(monkeypatch)
    _override_sessions()

    provider_id = uuid4()
    model_id = uuid4()
    credential_id = uuid4()

    class FakeExternalCatalogService:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.kwargs = kwargs

        def list_external_providers(self, **kwargs):  # type: ignore[no-untyped-def]
            return [
                SimpleNamespace(
                    id=provider_id,
                    name="OpenAI",
                    slug="openai",
                    is_active=True,
                )
            ]

        def list_external_provider_models(self, **kwargs):  # type: ignore[no-untyped-def]
            return [
                SimpleNamespace(
                    id=model_id,
                    provider_id=provider_id,
                    name="gpt-5",
                    slug="gpt-5",
                    is_active=True,
                )
            ]

        def list_external_credentials(self, **kwargs):  # type: ignore[no-untyped-def]
            return [
                SimpleNamespace(
                    id=credential_id,
                    provider_id=provider_id,
                    name="Credencial Principal",
                    is_active=True,
                )
            ]

    monkeypatch.setattr(external_catalog_route, "ExternalCatalogService", FakeExternalCatalogService)

    try:
        client = TestClient(app)
        providers_response = client.get("/api/v1/external/providers", headers=headers)
        assert providers_response.status_code == 200
        assert providers_response.json()["items"][0]["id"] == str(provider_id)

        models_response = client.get(f"/api/v1/external/providers/{provider_id}/models", headers=headers)
        assert models_response.status_code == 200
        assert models_response.json()["items"][0]["id"] == str(model_id)

        credentials_response = client.get("/api/v1/external/credentials", headers=headers)
        assert credentials_response.status_code == 200
        assert credentials_response.json()["items"][0]["id"] == str(credential_id)
    finally:
        app.dependency_overrides.clear()
