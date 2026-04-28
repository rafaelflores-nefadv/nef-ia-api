from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.services.token_service import ApiTokenService


def _auth_headers(monkeypatch):  # type: ignore[no-untyped-def]
    token_id = uuid4()

    def fake_validate_token(self, raw_token: str):  # type: ignore[no-untyped-def]
        assert raw_token == "ia_live_talent_bank_test"
        return SimpleNamespace(token=SimpleNamespace(id=token_id), permissions=[])

    def fake_log_usage(self, **kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(ApiTokenService, "validate_token", fake_validate_token)
    monkeypatch.setattr(ApiTokenService, "log_token_usage", fake_log_usage)
    return {"Authorization": "Bearer ia_live_talent_bank_test"}


def test_parse_resume_text_returns_structured_payload(monkeypatch) -> None:
    headers = _auth_headers(monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/api/v1/talentos/curriculos/parse-text",
        json={
            "texto": (
                "Maria Silva\n"
                "maria.silva@email.com\n"
                "(11) 98765-4321\n"
                "https://linkedin.com/in/mariasilva\n"
                "Objetivo\n"
                "Atuar como desenvolvedora backend.\n"
                "Habilidades\n"
                "- Python\n"
                "- FastAPI\n"
                "Idiomas\n"
                "- Ingles - Fluente\n"
            )
        },
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dados_pessoais"]["email"] == "maria.silva@email.com"
    assert payload["dados_pessoais"]["telefone"] == "(11) 98765-4321"
    assert payload["dados_pessoais"]["linkedin"] == "https://linkedin.com/in/mariasilva"
    assert payload["objetivo"] == "Atuar como desenvolvedora backend."
    assert "Python" in payload["habilidades"]


def test_parse_resume_text_rejects_empty_text(monkeypatch) -> None:
    headers = _auth_headers(monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/api/v1/talentos/curriculos/parse-text",
        json={"texto": "   "},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_resume_text"


def test_parse_resume_file_rejects_invalid_extension(monkeypatch) -> None:
    headers = _auth_headers(monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/api/v1/talentos/curriculos/parse",
        files={"file": ("curriculo.png", BytesIO(b"fake"), "image/png")},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_resume_file_extension"
