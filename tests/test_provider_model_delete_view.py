import os
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory
from django.urls import reverse

from core.services.provider_models_service import ProviderModelsServiceError
from models_catalog.views import provider_model_delete


def _build_request() -> object:
    request = RequestFactory().post("/models/1/excluir/")
    request.user = SimpleNamespace(is_authenticated=True)
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def test_provider_model_delete_success(monkeypatch) -> None:
    deleted = {"ok": False}

    class FakeModel:
        name = "GPT Teste"
        fastapi_model_id = None
        provider = SimpleNamespace(fastapi_provider_id=None)

        def delete(self) -> None:
            deleted["ok"] = True

    monkeypatch.setattr(
        "models_catalog.views.get_object_or_404",
        lambda model, pk: FakeModel(),  # type: ignore[no-untyped-def]
    )

    request = _build_request()
    response = provider_model_delete(request, pk=1)
    messages = [str(item.message) for item in get_messages(request)]

    assert response.status_code == 302
    assert response.url == reverse("models_catalog:list")
    assert deleted["ok"] is True
    assert any("excluido com sucesso" in message.lower() for message in messages)


def test_provider_model_delete_handles_protected_error(monkeypatch) -> None:
    class FakeModel:
        name = "GPT Bloqueado"
        fastapi_model_id = None
        provider = SimpleNamespace(fastapi_provider_id=None)

        def delete(self) -> None:
            raise ProtectedError("blocked", [object()])

    monkeypatch.setattr(
        "models_catalog.views.get_object_or_404",
        lambda model, pk: FakeModel(),  # type: ignore[no-untyped-def]
    )

    request = _build_request()
    response = provider_model_delete(request, pk=1)
    messages = [str(item.message) for item in get_messages(request)]

    assert response.status_code == 302
    assert response.url == reverse("models_catalog:list")
    assert any("vinculos" in message.lower() for message in messages)


def test_provider_model_delete_cancels_local_delete_when_remote_fails(monkeypatch) -> None:
    state = {"local_deleted": False}

    class FakeModel:
        name = "GPT Remoto"
        fastapi_model_id = "8f6dc8ca-0e6c-4ae7-98ed-7cc11d2ce2d1"
        slug = "gpt-4o-mini"
        provider = SimpleNamespace(fastapi_provider_id="d82f6853-e87e-4bf6-95ac-eadcfb5574d6")

        def delete(self) -> None:
            state["local_deleted"] = True

    class FakeProviderModelsService:
        def delete_remote_model_entry(self, *, provider, model_slug, fastapi_model_id):  # type: ignore[no-untyped-def]
            raise ProviderModelsServiceError("remote error")

    monkeypatch.setattr(
        "models_catalog.views.get_object_or_404",
        lambda model, pk: FakeModel(),  # type: ignore[no-untyped-def]
    )
    monkeypatch.setattr(
        "models_catalog.views.ProviderModelsService",
        lambda: FakeProviderModelsService(),  # type: ignore[no-untyped-def]
    )

    request = _build_request()
    response = provider_model_delete(request, pk=1)
    messages = [str(item.message) for item in get_messages(request)]

    assert response.status_code == 302
    assert response.url == reverse("models_catalog:list")
    assert state["local_deleted"] is False
    assert any("catalogo remoto" in message.lower() for message in messages)


def test_provider_model_delete_checks_remote_by_slug_when_id_missing(monkeypatch) -> None:
    state = {"local_deleted": False, "remote_called": False}

    class FakeModel:
        name = "GPT Remoto"
        fastapi_model_id = None
        slug = "gpt-4o-mini"
        provider = SimpleNamespace(fastapi_provider_id="d82f6853-e87e-4bf6-95ac-eadcfb5574d6")

        def delete(self) -> None:
            state["local_deleted"] = True

    class FakeProviderModelsService:
        def delete_remote_model_entry(self, *, provider, model_slug, fastapi_model_id):  # type: ignore[no-untyped-def]
            state["remote_called"] = True
            assert model_slug == "gpt-4o-mini"
            assert fastapi_model_id is None
            return 1

    monkeypatch.setattr(
        "models_catalog.views.get_object_or_404",
        lambda model, pk: FakeModel(),  # type: ignore[no-untyped-def]
    )
    monkeypatch.setattr(
        "models_catalog.views.ProviderModelsService",
        lambda: FakeProviderModelsService(),  # type: ignore[no-untyped-def]
    )

    request = _build_request()
    response = provider_model_delete(request, pk=1)
    messages = [str(item.message) for item in get_messages(request)]

    assert response.status_code == 302
    assert response.url == reverse("models_catalog:list")
    assert state["remote_called"] is True
    assert state["local_deleted"] is True
    assert any("excluido com sucesso" in message.lower() for message in messages)
