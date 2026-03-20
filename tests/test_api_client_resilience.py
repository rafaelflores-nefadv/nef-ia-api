import sys
import types

from django.db.utils import InterfaceError

from core.services.api_client import FastAPIClient


class _BrokenQuerySet:
    def select_related(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self

    def first(self):  # type: ignore[no-untyped-def]
        raise InterfaceError("simulated transient DB interface failure")


def test_load_db_integration_config_handles_interface_error(monkeypatch) -> None:
    fake_models = types.ModuleType("core.models")
    fake_models.FastAPIIntegrationConfig = types.SimpleNamespace(objects=_BrokenQuerySet())
    fake_models.FastAPIIntegrationToken = types.SimpleNamespace(objects=_BrokenQuerySet())
    monkeypatch.setitem(sys.modules, "core.models", fake_models)

    state = {"closed_old_connections": False, "warning_logged": False}

    monkeypatch.setattr(
        "core.services.api_client.close_old_connections",
        lambda: state.__setitem__("closed_old_connections", True),  # type: ignore[no-untyped-def]
    )
    monkeypatch.setattr(
        "core.services.api_client.logger.warning",
        lambda *args, **kwargs: state.__setitem__("warning_logged", True),  # type: ignore[no-untyped-def]
    )

    client = FastAPIClient.__new__(FastAPIClient)
    payload = client._load_db_integration_config()

    assert payload is None
    assert state["closed_old_connections"] is True
    assert state["warning_logged"] is True
