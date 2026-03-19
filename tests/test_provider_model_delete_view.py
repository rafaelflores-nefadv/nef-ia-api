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
