import os
from types import SimpleNamespace
from uuid import uuid4

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from test_automations.forms import TestAutomationCopyToOfficialForm, TestAutomationForm
from test_automations.models import TestAutomation
from test_automations.views import (
    TestAutomationCopyToOfficialView,
    TestAutomationCreateView,
    TestAutomationUpdateView,
    _decorate_output_contract_display,
)


def _build_request(path: str):
    request = RequestFactory().post(path)
    request.user = SimpleNamespace(is_authenticated=True)
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def _valid_form_data(*, provider_id: str, model_id: str, credential_id: str = "", debug_enabled: bool = False) -> dict[str, str]:
    payload = {
        "name": "Automacao Contrato",
        "provider_id": provider_id,
        "model_id": model_id,
        "credential_id": credential_id,
        "output_type": "spreadsheet_output",
        "result_parser": "tabular_structured",
        "result_formatter": "spreadsheet_tabular",
        "output_schema": '{"columns": ["linha_origem", "conteudo", "status"]}',
        "is_active": "on",
    }
    if debug_enabled:
        payload["debug_enabled"] = "on"
    return payload


def test_create_view_persists_output_contract(monkeypatch) -> None:
    provider_id = uuid4()
    model_id = uuid4()
    captured = {}

    form = TestAutomationForm(
        data=_valid_form_data(provider_id=str(provider_id), model_id=str(model_id), debug_enabled=True),
        provider_choices=[(str(provider_id), "Provider A")],
        model_choices=[(str(model_id), "Model A")],
        credential_choices=[],
    )
    assert form.is_valid() is True

    view = TestAutomationCreateView()
    view.request = _build_request("/automacoes-teste/nova/")

    monkeypatch.setattr(
        "test_automations.views.TestAutomation.objects.create",
        lambda **kwargs: captured.update(kwargs) or SimpleNamespace(id=uuid4()),
    )
    monkeypatch.setattr(
        view,
        "_resolve_runtime_snapshot",
        lambda **kwargs: (
            SimpleNamespace(id=provider_id, slug="openai"),
            SimpleNamespace(id=model_id, model_slug="gpt-4o-mini"),
            None,
        ),
    )
    monkeypatch.setattr(
        "test_automations.views._build_unique_slug",
        lambda *args, **kwargs: "slug-teste",
    )

    response = view.form_valid(form)

    assert response.status_code == 302
    assert captured["output_type"] == "spreadsheet_output"
    assert captured["result_parser"] == "tabular_structured"
    assert captured["result_formatter"] == "spreadsheet_tabular"
    assert captured["output_schema"] == {"columns": ["linha_origem", "conteudo", "status"]}
    assert captured["debug_enabled"] is True


def test_update_view_updates_output_contract(monkeypatch) -> None:
    provider_id = uuid4()
    model_id = uuid4()

    form = TestAutomationForm(
        data={
            **_valid_form_data(provider_id=str(provider_id), model_id=str(model_id), debug_enabled=True),
            "output_type": "text_output",
            "result_parser": "text_raw",
            "result_formatter": "text_plain",
            "output_schema": '{"file_name_template": "execution_{execution_id}.txt"}',
            "debug_enabled": "",
        },
        provider_choices=[(str(provider_id), "Provider A")],
        model_choices=[(str(model_id), "Model A")],
        credential_choices=[],
    )
    assert form.is_valid() is True

    saved = {"called": False}

    fake_automation = SimpleNamespace(
        id=uuid4(),
        name="Antes",
        provider_id=provider_id,
        model_id=model_id,
        credential_id=None,
        provider_slug="openai",
        model_slug="gpt-4o-mini",
        credential_name="",
        output_type="",
        result_parser="",
        result_formatter="",
        output_schema=None,
        debug_enabled=True,
    )

    def _save() -> None:
        saved["called"] = True

    fake_automation.save = _save

    view = TestAutomationUpdateView()
    view.request = _build_request(f"/automacoes-teste/{uuid4()}/editar/")
    view.automation = fake_automation

    monkeypatch.setattr(
        view,
        "_resolve_runtime_snapshot",
        lambda **kwargs: (
            SimpleNamespace(id=provider_id, slug="openai"),
            SimpleNamespace(id=model_id, model_slug="gpt-4o-mini"),
            None,
        ),
    )
    monkeypatch.setattr(
        "test_automations.views._build_unique_slug",
        lambda *args, **kwargs: "slug-teste",
    )

    response = view.form_valid(form)

    assert response.status_code == 302
    assert view.automation.output_type == "text_output"
    assert view.automation.result_parser == "text_raw"
    assert view.automation.result_formatter == "text_plain"
    assert view.automation.output_schema == {"file_name_template": "execution_{execution_id}.txt"}
    assert view.automation.debug_enabled is False
    assert saved["called"] is True


def test_form_shows_output_contract_options_in_portuguese() -> None:
    form = TestAutomationForm(provider_choices=[], model_choices=[], credential_choices=[])

    output_type_choices = dict(form.fields["output_type"].choices)
    parser_choices = dict(form.fields["result_parser"].choices)
    formatter_choices = dict(form.fields["result_formatter"].choices)

    assert output_type_choices["spreadsheet_output"] == "Planilha"
    assert output_type_choices["text_output"] == "Texto"
    assert parser_choices["tabular_structured"] == "Tabular estruturado"
    assert parser_choices["text_raw"] == "Texto bruto"
    assert formatter_choices["spreadsheet_tabular"] == "Planilha tabular"
    assert formatter_choices["text_plain"] == "Texto simples"
    assert form.fields["debug_enabled"].label == "Modo debug da automação"
    assert (
        form.fields["debug_enabled"].help_text
        == "Quando ativado, a automação gera também um arquivo técnico de diagnóstico da execução, útil para analisar a montagem do prompt, os dados utilizados, a resposta do modelo e o resultado final."
    )


def test_form_rejects_invalid_output_schema_json() -> None:
    provider_id = uuid4()
    model_id = uuid4()
    payload = _valid_form_data(provider_id=str(provider_id), model_id=str(model_id))
    payload["output_schema"] = "{invalido"

    form = TestAutomationForm(
        data=payload,
        provider_choices=[(str(provider_id), "Provider A")],
        model_choices=[(str(model_id), "Model A")],
        credential_choices=[],
    )

    assert form.is_valid() is False
    assert "output_schema" in form.errors


def test_form_rejects_incompatible_contract_combination() -> None:
    provider_id = uuid4()
    model_id = uuid4()
    payload = _valid_form_data(provider_id=str(provider_id), model_id=str(model_id))
    payload["output_type"] = "text_output"
    payload["result_parser"] = "tabular_structured"
    payload["result_formatter"] = "text_plain"

    form = TestAutomationForm(
        data=payload,
        provider_choices=[(str(provider_id), "Provider A")],
        model_choices=[(str(model_id), "Model A")],
        credential_choices=[],
    )

    assert form.is_valid() is False
    assert any("incompativel" in message.lower() for message in form.non_field_errors())


def test_contract_display_marks_explicit_and_legacy_modes() -> None:
    explicit_item = TestAutomation(
        id=uuid4(),
        name="Auto A",
        slug="auto-a",
        provider_id=uuid4(),
        model_id=uuid4(),
        provider_slug="openai",
        model_slug="gpt-4o-mini",
        credential_name="",
        output_type="spreadsheet_output",
        result_parser="tabular_structured",
        result_formatter="spreadsheet_tabular",
        output_schema={"columns": ["linha_origem", "conteudo"]},
        debug_enabled=True,
        is_active=True,
    )
    _decorate_output_contract_display(explicit_item)

    assert explicit_item.output_contract_source_label == "Contrato explicito"
    assert explicit_item.output_type_label == "Planilha"
    assert "chave" in explicit_item.output_schema_summary_label
    assert explicit_item.debug_mode_label == "Ativo"

    legacy_item = TestAutomation(
        id=uuid4(),
        name="Auto B",
        slug="auto-b",
        provider_id=uuid4(),
        model_id=uuid4(),
        provider_slug="openai",
        model_slug="gpt-4o-mini",
        credential_name="",
        output_type="",
        result_parser="",
        result_formatter="",
        output_schema=None,
        debug_enabled=False,
        is_active=True,
    )
    _decorate_output_contract_display(legacy_item)

    assert legacy_item.output_contract_source_label == "Padrao legado"
    assert legacy_item.has_explicit_output_contract is False
    assert legacy_item.debug_mode_label == "Desativado"


def test_old_automation_without_contract_remains_compatible() -> None:
    legacy_item = TestAutomation(
        id=uuid4(),
        name="Legado",
        slug="legado",
        provider_id=uuid4(),
        model_id=uuid4(),
        provider_slug="openai",
        model_slug="gpt-4o-mini",
        credential_name="",
        output_type="",
        result_parser="",
        result_formatter="",
        output_schema=None,
        debug_enabled=False,
        is_active=True,
    )

    assert legacy_item.has_explicit_output_contract is False
    assert legacy_item.output_schema_summary == "Padrao legado"


def test_copy_to_official_form_requires_owner_token() -> None:
    form = TestAutomationCopyToOfficialForm(data={"owner_token_id": ""}, owner_token_choices=[])

    assert form.is_valid() is False
    assert "owner_token_id" in form.errors


def test_copy_to_official_view_calls_fastapi_copy_flow(monkeypatch) -> None:
    owner_token_id = uuid4()
    source_automation_id = uuid4()
    captured = {}

    class _FakeService:
        def copy_test_automation_to_official(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return SimpleNamespace(
                owner_token_id=kwargs["owner_token_id"],
                automation_id=uuid4(),
                automation_name=kwargs["name"],
                prompt_id=uuid4(),
                prompt_version=1,
                source_test_automation_id=kwargs.get("source_test_automation_id"),
                source_test_prompt_id=kwargs.get("source_test_prompt_id"),
            )

    monkeypatch.setattr("test_automations.views.AutomationPromptsExecutionService", _FakeService)

    form = TestAutomationCopyToOfficialForm(
        data={"owner_token_id": str(owner_token_id)},
        owner_token_choices=[(str(owner_token_id), "Token destino")],
    )
    assert form.is_valid() is True

    view = TestAutomationCopyToOfficialView()
    view.request = _build_request(f"/automacoes-teste/{source_automation_id}/copiar-para-oficial/")
    view.automation = SimpleNamespace(
        id=source_automation_id,
        name="Automacao Teste",
        provider_id=uuid4(),
        model_id=uuid4(),
        credential_id=None,
        output_type="spreadsheet_output",
        result_parser="tabular_structured",
        result_formatter="spreadsheet_tabular",
        output_schema={"columns": ["numero_processo", "categoria"]},
        is_active=True,
    )
    view.source_prompt = SimpleNamespace(id=77, prompt_text="PROMPT VINCULADO")

    response = view.form_valid(form)

    assert response.status_code == 302
    assert captured["owner_token_id"] == owner_token_id
    assert captured["name"] == "Automacao Teste"
    assert captured["output_type"] == "spreadsheet_output"
    assert captured["result_parser"] == "tabular_structured"
    assert captured["result_formatter"] == "spreadsheet_tabular"
    assert captured["output_schema"] == {"columns": ["numero_processo", "categoria"]}
    assert captured["source_test_automation_id"] == source_automation_id
    assert captured["source_test_prompt_id"] == 77
    assert "debug_enabled" not in captured
