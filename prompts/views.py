from __future__ import annotations

from datetime import datetime
import json
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from core.services.automation_prompts_execution_service import (
    AutomationExecutionFileItem,
    AutomationExecutionStatusItem,
    AutomationPromptsExecutionService,
    AutomationPromptsExecutionServiceError,
    AutomationRuntimeReadItem,
    ProviderCredentialReadItem,
    ProviderModelReadItem,
    ProviderReadItem,
)

from .forms import (
    AutomationExecutionForm,
    OfficialAutomationForm,
    OfficialAutomationPromptForm,
)


OUTPUT_TYPE_LABELS: dict[str, str] = {
    "spreadsheet_output": "Planilha",
    "text_output": "Texto",
}

RESULT_PARSER_LABELS: dict[str, str] = {
    "tabular_structured": "Tabular estruturado",
    "text_raw": "Texto bruto",
}

RESULT_FORMATTER_LABELS: dict[str, str] = {
    "spreadsheet_tabular": "Planilha tabular",
    "text_plain": "Texto simples",
}


def _resolve_uuid(raw_value: str | UUID | None) -> UUID | None:
    raw = str(raw_value or "").strip()
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def _serialize_output_schema_for_form(output_schema: dict | str | None) -> str:
    if output_schema is None:
        return ""
    if isinstance(output_schema, str):
        return output_schema
    if isinstance(output_schema, dict):
        return json.dumps(output_schema, ensure_ascii=False, indent=2)
    return ""


def _label_output_type(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "Padrao legado"
    return OUTPUT_TYPE_LABELS.get(normalized, normalized)


def _label_result_parser(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "Padrao legado"
    return RESULT_PARSER_LABELS.get(normalized, normalized)


def _label_result_formatter(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "Padrao legado"
    return RESULT_FORMATTER_LABELS.get(normalized, normalized)


def _has_explicit_contract(item: AutomationRuntimeReadItem) -> bool:
    if str(item.output_type or "").strip():
        return True
    if str(item.result_parser or "").strip():
        return True
    if str(item.result_formatter or "").strip():
        return True
    if isinstance(item.output_schema, dict):
        return bool(item.output_schema)
    if isinstance(item.output_schema, str):
        return bool(item.output_schema.strip())
    return False


def _summarize_output_schema(output_schema: dict | str | None) -> str:
    if output_schema is None:
        return "Padrao legado"
    if isinstance(output_schema, str):
        raw = output_schema.strip()
        if not raw:
            return "Padrao legado"
        if len(raw) <= 80:
            return raw
        return f"{raw[:80]}..."
    if isinstance(output_schema, dict):
        if not output_schema:
            return "Padrao legado"
        keys = [str(key) for key in output_schema.keys()][:3]
        keys_display = ", ".join(keys)
        if len(output_schema) > 3:
            keys_display = f"{keys_display}, ..."
        return f"{len(output_schema)} chave(s): {keys_display}"
    return "Schema customizado"


def _decorate_output_contract_display(item: AutomationRuntimeReadItem) -> None:
    item.output_type_label = _label_output_type(item.output_type)
    item.result_parser_label = _label_result_parser(item.result_parser)
    item.result_formatter_label = _label_result_formatter(item.result_formatter)
    item.output_schema_summary_label = _summarize_output_schema(item.output_schema)
    item.has_explicit_output_contract = _has_explicit_contract(item)
    item.output_contract_source_label = (
        "Contrato explicito" if item.has_explicit_output_contract else "Padrao legado"
    )
    item.output_contract_source_css = (
        "status-success" if item.has_explicit_output_contract else "status-neutral"
    )


def _load_provider_options() -> tuple[list[ProviderReadItem], str, list[str]]:
    service = AutomationPromptsExecutionService()
    try:
        return service.list_providers(), "api", []
    except AutomationPromptsExecutionServiceError as exc:
        return [], "unavailable", [str(exc)]


def _load_provider_models(provider_id: UUID) -> tuple[list[ProviderModelReadItem], list[str]]:
    service = AutomationPromptsExecutionService()
    try:
        return service.list_provider_models(provider_id=provider_id), []
    except AutomationPromptsExecutionServiceError as exc:
        return [], [str(exc)]


def _load_provider_credentials(provider_id: UUID) -> tuple[list[ProviderCredentialReadItem], list[str]]:
    service = AutomationPromptsExecutionService()
    try:
        return service.list_provider_credentials(provider_id=provider_id), []
    except AutomationPromptsExecutionServiceError as exc:
        return [], [str(exc)]


def _load_official_automation_or_404(automation_id_raw: str | UUID | None) -> AutomationRuntimeReadItem:
    automation_id = _resolve_uuid(automation_id_raw)
    if automation_id is None:
        raise Http404("Automacao oficial invalida.")
    try:
        automation = AutomationPromptsExecutionService().get_automation_runtime(
            automation_id=automation_id,
        )
    except AutomationPromptsExecutionServiceError as exc:
        raise Http404("Automacao oficial nao encontrada.") from exc
    if bool(getattr(automation, "is_test_automation", False)):
        raise Http404("Automacao oficial nao encontrada.")
    return automation


class OfficialAutomationListView(LoginRequiredMixin, ListView):
    template_name = "prompts/list.html"
    context_object_name = "automations"

    def get_queryset(self):
        payload = AutomationPromptsExecutionService().list_automations_runtime()
        self.integration_source = payload["source"]
        self.integration_warnings = payload["warnings"]
        items = [item for item in payload["items"] if not bool(getattr(item, "is_test_automation", False))]

        search_query = str(self.request.GET.get("q") or "").strip().lower()
        selected_status = str(self.request.GET.get("status") or "").strip().lower()
        filtered: list[AutomationRuntimeReadItem] = []
        for item in items:
            name = str(item.automation_name or "").strip().lower()
            if search_query and search_query not in name:
                continue
            if selected_status == "ativo" and not bool(item.automation_is_active):
                continue
            if selected_status == "inativo" and bool(item.automation_is_active):
                continue
            _decorate_output_contract_display(item)
            filtered.append(item)
        self.total_count = len(items)
        return filtered

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items = context.get("automations") or []
        context.update(
            {
                "page_title": "Automações",
                "page_subtitle": "CRUD administrativo das automações oficiais.",
                "active_menu": "automacoes_oficiais",
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
                "search_query": str(self.request.GET.get("q") or "").strip(),
                "selected_status": str(self.request.GET.get("status") or "").strip().lower(),
                "total_count": getattr(self, "total_count", len(items)),
                "filtered_count": len(items),
                "list_counter_label": f"{len(items)} automacao(oes) oficial(is)",
            }
        )
        return context


class OfficialAutomationDetailView(LoginRequiredMixin, TemplateView):
    template_name = "prompts/detail.html"
    automation: AutomationRuntimeReadItem

    def dispatch(self, request, *args, **kwargs):
        automation_id = _resolve_uuid(kwargs.get("automation_id"))
        if automation_id is None:
            raise Http404("Automacao oficial invalida.")
        try:
            self.automation = AutomationPromptsExecutionService().get_automation_runtime(
                automation_id=automation_id,
            )
        except AutomationPromptsExecutionServiceError as exc:
            raise Http404("Automacao oficial nao encontrada.") from exc
        if bool(getattr(self.automation, "is_test_automation", False)):
            raise Http404("Automacao oficial nao encontrada.")
        _decorate_output_contract_display(self.automation)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": self.automation.automation_name,
                "active_menu": "automacoes_oficiais",
                "automation": self.automation,
                "integration_source": "api",
                "integration_warnings": [],
            }
        )
        return context


class OfficialAutomationPromptDetailView(LoginRequiredMixin, TemplateView):
    template_name = "prompts/prompt_detail.html"
    automation: AutomationRuntimeReadItem

    def dispatch(self, request, *args, **kwargs):
        self.automation = _load_official_automation_or_404(kwargs.get("automation_id"))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": f"Prompt oficial · {self.automation.automation_name}",
                "active_menu": "automacoes_oficiais",
                "automation": self.automation,
                "integration_source": "api",
                "integration_warnings": [],
            }
        )
        return context


class OfficialAutomationPromptUpdateView(LoginRequiredMixin, FormView):
    template_name = "prompts/prompt_form.html"
    form_class = OfficialAutomationPromptForm
    automation: AutomationRuntimeReadItem

    def dispatch(self, request, *args, **kwargs):
        self.automation = _load_official_automation_or_404(kwargs.get("automation_id"))
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {
            "prompt_text": str(self.automation.prompt_text or ""),
        }

    def form_valid(self, form):
        provider_id = self.automation.provider_id
        model_id = self.automation.model_id
        if provider_id is None or model_id is None:
            form.add_error(
                None,
                "Nao foi possivel editar o prompt porque a automacao nao possui runtime completo (provider/model).",
            )
            return self.form_invalid(form)

        service = AutomationPromptsExecutionService()
        output_schema = self.automation.output_schema if isinstance(self.automation.output_schema, dict) else None
        if output_schema is None and isinstance(self.automation.output_schema, str):
            raw_schema = str(self.automation.output_schema).strip()
            if raw_schema:
                try:
                    parsed_schema = json.loads(raw_schema)
                except json.JSONDecodeError:
                    form.add_error(
                        None,
                        "Nao foi possivel preservar o schema tecnico atual. Edite por 'Editar automacao' para ajustar o contrato.",
                    )
                    return self.form_invalid(form)
                if not isinstance(parsed_schema, dict):
                    form.add_error(
                        None,
                        "Schema tecnico atual invalido para este fluxo. Use 'Editar automacao' para ajustar o contrato.",
                    )
                    return self.form_invalid(form)
                output_schema = parsed_schema
        try:
            service.update_automation_runtime(
                automation_id=self.automation.automation_id,
                name=str(self.automation.automation_name or "").strip(),
                provider_id=provider_id,
                model_id=model_id,
                credential_id=self.automation.credential_id,
                output_type=str(self.automation.output_type or "").strip() or None,
                result_parser=str(self.automation.result_parser or "").strip() or None,
                result_formatter=str(self.automation.result_formatter or "").strip() or None,
                output_schema=output_schema,
                prompt_text=str(form.cleaned_data.get("prompt_text") or "").strip(),
            )
        except AutomationPromptsExecutionServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, "Prompt oficial atualizado com sucesso.")
        return redirect("prompts:prompt_detail", automation_id=self.automation.automation_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Editar prompt oficial",
                "form_title": "Editar prompt oficial",
                "form_subtitle": "Atualize apenas o prompt oficial vinculado a esta automacao.",
                "active_menu": "automacoes_oficiais",
                "submit_label": "Salvar prompt",
                "automation": self.automation,
                "integration_source": "api",
                "integration_warnings": [],
            }
        )
        return context


class _BaseOfficialAutomationFormView(LoginRequiredMixin, FormView):
    form_class = OfficialAutomationForm
    automation: AutomationRuntimeReadItem

    def _resolve_selected_provider_id(self, *, fallback: UUID | None = None) -> UUID | None:
        raw = (
            self.request.POST.get("provider_id")
            if self.request.method.upper() == "POST"
            else self.request.GET.get("provider_id")
        )
        return _resolve_uuid(raw or fallback)

    def _build_form_kwargs(self) -> dict:
        kwargs = super().get_form_kwargs()
        provider_options, provider_source, provider_warnings = _load_provider_options()
        self.integration_source = provider_source
        self.integration_warnings = list(provider_warnings)

        selected_provider = self._resolve_selected_provider_id(fallback=self.automation.provider_id)
        selected_model = (
            _resolve_uuid(self.request.POST.get("model_id"))
            if self.request.method.upper() == "POST"
            else None
        ) or self.automation.model_id
        selected_credential = (
            _resolve_uuid(self.request.POST.get("credential_id"))
            if self.request.method.upper() == "POST"
            else None
        ) or self.automation.credential_id
        selected_output_type = (
            str(self.request.POST.get("output_type") or "").strip()
            if self.request.method.upper() == "POST"
            else str(getattr(self.automation, "output_type", "") or "").strip()
        )
        selected_result_parser = (
            str(self.request.POST.get("result_parser") or "").strip()
            if self.request.method.upper() == "POST"
            else str(getattr(self.automation, "result_parser", "") or "").strip()
        )
        selected_result_formatter = (
            str(self.request.POST.get("result_formatter") or "").strip()
            if self.request.method.upper() == "POST"
            else str(getattr(self.automation, "result_formatter", "") or "").strip()
        )
        initial_output_schema = (
            str(self.request.POST.get("output_schema") or "").strip()
            if self.request.method.upper() == "POST"
            else _serialize_output_schema_for_form(getattr(self.automation, "output_schema", None))
        )

        provider_choices = [(str(item.id), f"{item.name} ({item.slug})") for item in provider_options]
        model_choices: list[tuple[str, str]] = []
        credential_choices: list[tuple[str, str]] = []

        if selected_provider is not None:
            provider_models, model_warnings = _load_provider_models(selected_provider)
            provider_credentials, credential_warnings = _load_provider_credentials(selected_provider)
            self.integration_warnings.extend(model_warnings)
            self.integration_warnings.extend(credential_warnings)
            model_choices = [
                (str(item.id), f"{item.model_name} ({item.model_slug})")
                for item in provider_models
            ]
            credential_choices = [
                (str(item.id), item.credential_name)
                for item in provider_credentials
            ]

        if (
            self.automation.provider_id == selected_provider
            and self.automation.model_id is not None
            and all(str(self.automation.model_id) != value for value, _ in model_choices)
        ):
            model_choices.append(
                (
                    str(self.automation.model_id),
                    f"{self.automation.model_slug or self.automation.model_id} ({self.automation.model_id})",
                )
            )
        if (
            self.automation.provider_id == selected_provider
            and self.automation.credential_id is not None
            and all(str(self.automation.credential_id) != value for value, _ in credential_choices)
        ):
            credential_label = self.automation.credential_name or str(self.automation.credential_id)
            credential_choices.append((str(self.automation.credential_id), credential_label))

        kwargs["provider_choices"] = provider_choices
        kwargs["model_choices"] = model_choices
        kwargs["credential_choices"] = credential_choices
        kwargs["selected_provider"] = str(selected_provider) if selected_provider is not None else None
        kwargs["selected_model"] = str(selected_model) if selected_model is not None else None
        kwargs["selected_credential"] = str(selected_credential) if selected_credential is not None else None
        kwargs["selected_output_type"] = selected_output_type or None
        kwargs["selected_result_parser"] = selected_result_parser or None
        kwargs["selected_result_formatter"] = selected_result_formatter or None
        kwargs["initial_output_schema"] = initial_output_schema
        return kwargs


class OfficialAutomationUpdateView(_BaseOfficialAutomationFormView):
    template_name = "prompts/automation_form.html"

    def dispatch(self, request, *args, **kwargs):
        automation_id = _resolve_uuid(kwargs.get("automation_id"))
        if automation_id is None:
            raise Http404("Automacao oficial invalida.")
        try:
            self.automation = AutomationPromptsExecutionService().get_automation_runtime(
                automation_id=automation_id,
            )
        except AutomationPromptsExecutionServiceError as exc:
            raise Http404("Automacao oficial nao encontrada.") from exc
        if bool(getattr(self.automation, "is_test_automation", False)):
            raise Http404("Automacao oficial nao encontrada.")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {
            "name": self.automation.automation_name,
            "provider_id": str(self.automation.provider_id or ""),
            "model_id": str(self.automation.model_id or ""),
            "credential_id": str(self.automation.credential_id or ""),
            "output_type": str(self.automation.output_type or ""),
            "result_parser": str(self.automation.result_parser or ""),
            "result_formatter": str(self.automation.result_formatter or ""),
            "output_schema": _serialize_output_schema_for_form(self.automation.output_schema),
            "prompt_text": str(self.automation.prompt_text or ""),
            "is_active": bool(self.automation.automation_is_active),
        }

    def get_form_kwargs(self):
        return self._build_form_kwargs()

    def form_valid(self, form):
        provider_id = _resolve_uuid(form.cleaned_data.get("provider_id"))
        model_id = _resolve_uuid(form.cleaned_data.get("model_id"))
        credential_id = _resolve_uuid(form.cleaned_data.get("credential_id"))
        if provider_id is None or model_id is None:
            form.add_error(None, "Provider/model invalidos.")
            return self.form_invalid(form)

        service = AutomationPromptsExecutionService()
        try:
            service.update_automation_runtime(
                automation_id=self.automation.automation_id,
                name=str(form.cleaned_data.get("name") or "").strip(),
                provider_id=provider_id,
                model_id=model_id,
                credential_id=credential_id,
                output_type=str(form.cleaned_data.get("output_type") or "").strip() or None,
                result_parser=str(form.cleaned_data.get("result_parser") or "").strip() or None,
                result_formatter=str(form.cleaned_data.get("result_formatter") or "").strip() or None,
                output_schema=form.cleaned_data.get("output_schema_parsed"),
                prompt_text=str(form.cleaned_data.get("prompt_text") or "").strip(),
            )
            service.set_automation_status(
                automation_id=self.automation.automation_id,
                is_active=bool(form.cleaned_data.get("is_active", False)),
            )
        except AutomationPromptsExecutionServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, "Automacao oficial atualizada com sucesso.")
        return redirect("prompts:detail", automation_id=self.automation.automation_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Editar automacao oficial",
                "form_title": "Editar automacao oficial",
                "form_subtitle": "Atualize runtime, contrato, status e prompt oficial vinculado.",
                "active_menu": "automacoes_oficiais",
                "submit_label": "Salvar alteracoes",
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
                "provider_models_url": reverse("prompts:provider_models"),
                "provider_credentials_url": reverse("prompts:provider_credentials"),
                "is_editing": True,
                "automation": self.automation,
            }
        )
        return context


class OfficialAutomationDeleteView(LoginRequiredMixin, TemplateView):
    template_name = "prompts/delete.html"
    automation: AutomationRuntimeReadItem

    def dispatch(self, request, *args, **kwargs):
        automation_id = _resolve_uuid(kwargs.get("automation_id"))
        if automation_id is None:
            raise Http404("Automacao oficial invalida.")
        try:
            self.automation = AutomationPromptsExecutionService().get_automation_runtime(
                automation_id=automation_id,
            )
        except AutomationPromptsExecutionServiceError as exc:
            raise Http404("Automacao oficial nao encontrada.") from exc
        if bool(getattr(self.automation, "is_test_automation", False)):
            raise Http404("Automacao oficial nao encontrada.")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        service = AutomationPromptsExecutionService()
        try:
            service.delete_automation(automation_id=self.automation.automation_id)
        except AutomationPromptsExecutionServiceError as exc:
            messages.error(request, str(exc))
            return redirect("prompts:detail", automation_id=self.automation.automation_id)
        messages.success(request, f'Automacao oficial "{self.automation.automation_name}" excluida com sucesso.')
        return redirect("prompts:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Excluir automacao oficial",
                "active_menu": "automacoes_oficiais",
                "automation": self.automation,
            }
        )
        return context


@login_required
@require_POST
def official_automation_toggle_status(request, automation_id: UUID):
    service = AutomationPromptsExecutionService()
    try:
        automation = service.get_automation_runtime(automation_id=automation_id)
        updated = service.set_automation_status(
            automation_id=automation_id,
            is_active=not bool(automation.automation_is_active),
        )
    except AutomationPromptsExecutionServiceError as exc:
        messages.error(request, f"Nao foi possivel atualizar o status da automacao oficial: {exc}")
        return redirect("prompts:list")

    if updated.automation_is_active:
        messages.success(request, "Automacao oficial ativada com sucesso.")
    else:
        messages.success(request, "Automacao oficial desativada com sucesso.")
    return redirect("prompts:list")


class OfficialAutomationProviderModelsView(LoginRequiredMixin, View):
    def get(self, request):
        provider_id = _resolve_uuid(request.GET.get("provider_id"))
        if provider_id is None:
            return JsonResponse({"ok": False, "error": "Provider invalido.", "items": []}, status=400)

        models, warnings = _load_provider_models(provider_id=provider_id)
        return JsonResponse(
            {
                "ok": True,
                "items": [
                    {
                        "id": str(item.id),
                        "provider_id": str(item.provider_id),
                        "model_name": item.model_name,
                        "model_slug": item.model_slug,
                    }
                    for item in models
                ],
                "warnings": warnings,
            }
        )


class OfficialAutomationProviderCredentialsView(LoginRequiredMixin, View):
    def get(self, request):
        provider_id = _resolve_uuid(request.GET.get("provider_id"))
        if provider_id is None:
            return JsonResponse({"ok": False, "error": "Provider invalido.", "items": []}, status=400)

        credentials, warnings = _load_provider_credentials(provider_id=provider_id)
        return JsonResponse(
            {
                "ok": True,
                "items": [
                    {
                        "id": str(item.id),
                        "provider_id": str(item.provider_id),
                        "credential_name": item.credential_name,
                    }
                    for item in credentials
                ],
                "warnings": warnings,
            }
        )


def _parse_json_request_payload(request) -> dict[str, object]:
    raw_body = request.body.decode("utf-8") if request.body else ""
    if not raw_body.strip():
        return {}
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError("Payload JSON invalido.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Payload JSON deve ser um objeto.")
    return payload


def _payload_bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "sim"}:
        return True
    if normalized in {"0", "false", "no", "off", "nao", "não"}:
        return False
    return default


def _assistant_error_response(exc: Exception) -> JsonResponse:
    if isinstance(exc, AutomationPromptsExecutionServiceError):
        status_code = int(exc.status_code) if exc.status_code is not None else 502
        return JsonResponse(
            {
                "ok": False,
                "error": str(exc),
                "code": str(exc.code or ""),
            },
            status=max(status_code, 400),
        )
    return JsonResponse(
        {
            "ok": False,
            "error": str(exc) or "Falha inesperada ao processar solicitacao.",
        },
        status=400,
    )


class OfficialExpectedResultAssistantView(LoginRequiredMixin, TemplateView):
    template_name = "prompts/expected_result_assistant.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payload = AutomationPromptsExecutionService().list_automations_runtime()
        integration_source = payload.get("source") or "unavailable"
        integration_warnings = payload.get("warnings") or []
        items = payload.get("items") or []
        automations = [
            item
            for item in items
            if isinstance(item, AutomationRuntimeReadItem) and not bool(getattr(item, "is_test_automation", False))
        ]
        automations.sort(key=lambda item: str(item.automation_name or "").lower())
        context.update(
            {
                "page_title": "Assistente de resultado esperado",
                "active_menu": "assistente_resultado_esperado",
                "integration_source": integration_source,
                "integration_warnings": integration_warnings,
                "automations": automations,
                "list_counter_label": f"{len(automations)} automacao(oes) oficial(is) disponivel(is)",
                "assistant_notice": (
                    "Se o resultado esperado exigir inclusao ou remocao de campos, confirme primeiro a atualizacao "
                    "dos campos de saida da automacao antes da execucao. Se nao houver alteracao estrutural, "
                    "a automacao pode ser executada com a configuracao atual."
                ),
            }
        )
        return context


class OfficialExpectedResultAssistantSimplePreviewApiView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            payload = _parse_json_request_payload(request)
            automation_id = _resolve_uuid(payload.get("automation_id"))
            raw_prompt = str(payload.get("raw_prompt") or "").strip()
            expected_result_description = str(payload.get("expected_result_description") or "").strip() or None
            if automation_id is None:
                raise ValueError("Selecione uma automacao oficial valida.")
            if not raw_prompt:
                raise ValueError("Informe o prompt para analise.")
            data = AutomationPromptsExecutionService().prompt_refinement_preview(
                automation_id=automation_id,
                raw_prompt=raw_prompt,
                expected_result_description=expected_result_description,
            )
            return JsonResponse({"ok": True, "data": data})
        except Exception as exc:
            return _assistant_error_response(exc)


class OfficialExpectedResultAssistantSimpleApplyApiView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            payload = _parse_json_request_payload(request)
            automation_id = _resolve_uuid(payload.get("automation_id"))
            if automation_id is None:
                raise ValueError("Selecione uma automacao oficial valida.")
            corrected_prompt = str(payload.get("corrected_prompt") or "").strip() or None
            apply_prompt_update = _payload_bool(payload.get("apply_prompt_update"), default=False)
            apply_schema_update = _payload_bool(payload.get("apply_schema_update"), default=False)
            create_new_prompt_version = _payload_bool(payload.get("create_new_prompt_version"), default=False)
            proposed_output_schema = payload.get("proposed_output_schema")
            if proposed_output_schema is not None and not isinstance(proposed_output_schema, dict):
                raise ValueError("proposed_output_schema deve ser um objeto JSON.")
            data = AutomationPromptsExecutionService().prompt_refinement_apply(
                automation_id=automation_id,
                corrected_prompt=corrected_prompt,
                apply_prompt_update=apply_prompt_update,
                apply_schema_update=apply_schema_update,
                proposed_output_schema=proposed_output_schema,
                create_new_prompt_version=create_new_prompt_version,
            )
            return JsonResponse({"ok": True, "data": data})
        except Exception as exc:
            return _assistant_error_response(exc)


class OfficialExpectedResultAssistantAdvancedPreviewApiView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            payload = _parse_json_request_payload(request)
            automation_id = _resolve_uuid(payload.get("automation_id"))
            raw_prompt = str(payload.get("raw_prompt") or "").strip()
            expected_result_description = str(payload.get("expected_result_description") or "").strip() or None
            if automation_id is None:
                raise ValueError("Selecione uma automacao oficial valida.")
            if not raw_prompt:
                raise ValueError("Informe o prompt para analise avancada.")
            data = AutomationPromptsExecutionService().prompt_refinement_advanced_preview(
                automation_id=automation_id,
                raw_prompt=raw_prompt,
                expected_result_description=expected_result_description,
            )
            return JsonResponse({"ok": True, "data": data})
        except Exception as exc:
            return _assistant_error_response(exc)


class OfficialExpectedResultAssistantAdvancedApplyApiView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            payload = _parse_json_request_payload(request)
            automation_id = _resolve_uuid(payload.get("automation_id"))
            if automation_id is None:
                raise ValueError("Selecione uma automacao oficial valida.")
            corrected_prompt = str(payload.get("corrected_prompt") or "").strip() or None
            expected_result_description = str(payload.get("expected_result_description") or "").strip() or None
            apply_prompt_update = _payload_bool(payload.get("apply_prompt_update"), default=False)
            apply_schema_update = _payload_bool(payload.get("apply_schema_update"), default=False)
            create_new_prompt_version = _payload_bool(payload.get("create_new_prompt_version"), default=False)
            confirm_manual_review = _payload_bool(payload.get("confirm_manual_review"), default=False)
            allow_field_removals = _payload_bool(payload.get("allow_field_removals"), default=True)
            reviewed_output_schema = payload.get("reviewed_output_schema")
            if reviewed_output_schema is not None and not isinstance(reviewed_output_schema, dict):
                raise ValueError("reviewed_output_schema deve ser um objeto JSON.")
            data = AutomationPromptsExecutionService().prompt_refinement_advanced_apply(
                automation_id=automation_id,
                corrected_prompt=corrected_prompt,
                expected_result_description=expected_result_description,
                apply_prompt_update=apply_prompt_update,
                apply_schema_update=apply_schema_update,
                reviewed_output_schema=reviewed_output_schema,
                create_new_prompt_version=create_new_prompt_version,
                confirm_manual_review=confirm_manual_review,
                allow_field_removals=allow_field_removals,
            )
            return JsonResponse({"ok": True, "data": data})
        except Exception as exc:
            return _assistant_error_response(exc)


def _execution_status_meta(status: str) -> dict[str, str]:
    table = {
        "queued": {"label": "Na fila", "css_class": "status-neutral"},
        "pending": {"label": "Pendente", "css_class": "status-neutral"},
        "processing": {"label": "Processando", "css_class": "status-warning"},
        "generating_output": {"label": "Gerando resultado", "css_class": "status-warning"},
        "completed": {"label": "Concluída", "css_class": "status-success"},
        "failed": {"label": "Falhou", "css_class": "status-danger"},
    }
    normalized = str(status or "").strip().lower()
    return table.get(normalized, {"label": normalized or "Desconhecido", "css_class": "status-neutral"})


def _execution_status_message(*, status: str, error_message: str = "") -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"queued", "pending"}:
        return "Preparando execução. Aguarde os próximos passos."
    if normalized == "processing":
        return "Arquivo enviado. Processando conteúdo da execução."
    if normalized == "generating_output":
        return "Análise concluída. Gerando resultado final."
    if normalized == "completed":
        return "Execução concluída. Resultado pronto para download."
    if normalized == "failed":
        return error_message or "A execução falhou. Revise a mensagem de erro abaixo."
    return "Status da execução atualizado."


def _is_terminal_status(status: str) -> bool:
    normalized = str(status or "").strip().lower()
    return normalized in {"completed", "failed"}


def _resolve_progress_percent(*, status: str, explicit_progress: int | None) -> int:
    if explicit_progress is not None:
        return max(0, min(100, int(explicit_progress)))
    normalized = str(status or "").strip().lower()
    inferred = {
        "queued": 5,
        "pending": 15,
        "processing": 55,
        "generating_output": 85,
        "completed": 100,
        "failed": 100,
    }
    return inferred.get(normalized, 0)


def _format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < (1024 * 1024):
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < (1024 * 1024 * 1024):
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _format_datetime_display(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%d/%m/%Y %H:%M:%S")


def _build_file_rows(files: list[AutomationExecutionFileItem]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for file_item in files:
        rows.append(
            {
                "id": file_item.id,
                "file_type": file_item.file_type,
                "file_name": file_item.file_name,
                "file_size": file_item.file_size,
                "file_size_display": _format_file_size(file_item.file_size),
                "created_at": file_item.created_at,
                "created_at_display": _format_datetime_display(file_item.created_at),
                "mime_type": file_item.mime_type or "-",
                "download_url": reverse("prompts:execution_file_download", kwargs={"file_id": str(file_item.id)}),
            }
        )
    return rows


def _serialize_file_rows(file_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    for item in file_rows:
        serialized.append(
            {
                "id": str(item["id"]),
                "file_type": item["file_type"],
                "file_name": item["file_name"],
                "file_size": item["file_size"],
                "file_size_display": item["file_size_display"],
                "created_at": (
                    item["created_at"].isoformat() if isinstance(item.get("created_at"), datetime) else None
                ),
                "created_at_display": item["created_at_display"],
                "mime_type": item["mime_type"],
                "download_url": item["download_url"],
            }
        )
    return serialized


class AutomationPromptListView(LoginRequiredMixin, ListView):
    template_name = "prompts/list.html"
    context_object_name = "automations"

    def get_queryset(self):
        payload = AutomationPromptsExecutionService().list_automations_runtime()
        self.integration_source = payload["source"]
        self.integration_warnings = payload["warnings"]
        return [item for item in payload["items"] if not bool(getattr(item, "is_test_automation", False))]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items = context.get("automations") or []
        context.update(
            {
                "page_title": "Prompts de automação",
                "page_subtitle": "Fonte oficial via FastAPI e banco compartilhado (automations + automation_prompts).",
                "active_menu": "prompts",
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
                "total_count": len(items),
                "list_counter_label": f"{len(items)} automação(ões) carregada(s)",
            }
        )
        return context


class AutomationExecutionCreateView(LoginRequiredMixin, FormView):
    template_name = "prompts/form.html"
    form_class = AutomationExecutionForm
    selected_automation: AutomationRuntimeReadItem | None = None
    selected_automation_id: UUID | None = None
    automation_id_is_invalid = False
    integration_source = "api"
    integration_warnings: list[str] = []

    def _extract_selected_automation_id(self) -> UUID | None:
        raw = str(
            self.request.POST.get("automation_id")
            or self.request.GET.get("automation_id")
            or self.request.GET.get("automation")
            or ""
        ).strip()
        if not raw:
            return None
        try:
            return UUID(raw)
        except ValueError:
            self.automation_id_is_invalid = True
            return None

    def dispatch(self, request, *args, **kwargs):
        self.automation_id_is_invalid = False
        self.selected_automation = None
        self.selected_automation_id = self._extract_selected_automation_id()
        if self.selected_automation_id is None:
            if self.automation_id_is_invalid:
                messages.error(request, "Automação informada para execução é inválida.")
            else:
                messages.error(request, "Selecione um prompt com automação válida antes de executar.")
            return redirect("prompts:list")

        service = AutomationPromptsExecutionService()
        try:
            self.selected_automation = service.get_automation_runtime(automation_id=self.selected_automation_id)
        except AutomationPromptsExecutionServiceError as exc:
            messages.error(request, f"Não foi possível carregar a automação selecionada: {exc}")
            return redirect("prompts:list")

        if bool(getattr(self.selected_automation, "is_test_automation", False)):
            messages.error(request, "A automação selecionada é de teste e não pode ser executada neste fluxo.")
            return redirect("prompts:list")

        self.integration_source = "api"
        self.integration_warnings = []
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        selected = self.selected_automation
        if selected is None:
            form.add_error(None, "Automação não encontrada para esta execução.")
            return self.form_invalid(form)

        uploaded_file = form.cleaned_data["request_file"]
        service = AutomationPromptsExecutionService()
        try:
            result = service.start_execution(
                automation_id=selected.automation_id,
                uploaded_file=uploaded_file,
            )
        except AutomationPromptsExecutionServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(
            self.request,
            "Execucao real iniciada com sucesso. Acompanhe o progresso abaixo.",
        )
        return redirect("prompts:execution_detail", execution_id=str(result.execution_id))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Executar automação",
                "form_title": "Executar automação",
                "form_subtitle": "A automação usada na execução é a já vinculada ao prompt selecionado.",
                "active_menu": "prompts",
                "integration_source": getattr(self, "integration_source", "api"),
                "integration_warnings": getattr(self, "integration_warnings", []),
                "selected_automation": self.selected_automation,
                "selected_automation_id": str(self.selected_automation_id) if self.selected_automation_id else "",
                "submit_label": "Subir arquivo e executar",
            }
        )
        return context


class AutomationExecutionDetailView(LoginRequiredMixin, TemplateView):
    template_name = "prompts/execution_detail.html"
    execution_status: AutomationExecutionStatusItem | None = None
    execution_files: list[AutomationExecutionFileItem] = []

    def _parse_execution_id(self) -> UUID:
        execution_id_raw = str(self.kwargs.get("execution_id") or "").strip()
        try:
            return UUID(execution_id_raw)
        except ValueError as exc:
            raise Http404("ID de execução inválido.") from exc

    def _load_execution(self, *, execution_id: UUID) -> None:
        service = AutomationPromptsExecutionService()
        self.execution_status = service.get_execution_status(execution_id=execution_id)
        self.integration_source = "api"
        self.integration_warnings = []
        try:
            self.execution_files = service.list_execution_files(execution_id=execution_id)
        except AutomationPromptsExecutionServiceError as exc:
            self.execution_files = []
            self.integration_source = "api_partial"
            self.integration_warnings = [str(exc)]

    def get(self, request, *args, **kwargs):
        execution_id = self._parse_execution_id()
        try:
            self._load_execution(execution_id=execution_id)
        except AutomationPromptsExecutionServiceError as exc:
            messages.error(
                request,
                f"Não foi possível carregar a execução real: {exc}",
            )
            return redirect("prompts:list")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        execution = self.execution_status
        files = self.execution_files
        if execution is None:
            execution = AutomationExecutionStatusItem(
                execution_id=UUID("00000000-0000-0000-0000-000000000000"),
                analysis_request_id=UUID("00000000-0000-0000-0000-000000000000"),
                automation_id=UUID("00000000-0000-0000-0000-000000000000"),
                request_file_id=None,
                request_file_name=None,
                prompt_override_applied=False,
                status="unknown",
                progress=None,
                started_at=None,
                finished_at=None,
                error_message="",
                created_at=None,
                checked_at=None,
            )
        status_meta = _execution_status_meta(execution.status)
        is_terminal = _is_terminal_status(execution.status)
        progress_percent = _resolve_progress_percent(status=execution.status, explicit_progress=execution.progress)
        status_message = _execution_status_message(status=execution.status, error_message=execution.error_message)

        file_rows = _build_file_rows(files)

        context.update(
            {
                "page_title": f"Execucao real {execution.execution_id}",
                "active_menu": "prompts",
                "execution": execution,
                "status_label": status_meta["label"],
                "status_css_class": status_meta["css_class"],
                "status_message": status_message,
                "is_terminal": is_terminal,
                "progress_percent": progress_percent,
                "file_rows": file_rows,
                "status_endpoint_url": reverse(
                    "prompts:execution_status",
                    kwargs={"execution_id": str(execution.execution_id)},
                ),
                "integration_source": getattr(self, "integration_source", "api"),
                "integration_warnings": getattr(self, "integration_warnings", []),
            }
        )
        return context


class AutomationExecutionStatusView(LoginRequiredMixin, View):
    def get(self, request, execution_id: str):
        try:
            execution_uuid = UUID(str(execution_id))
        except ValueError:
            return JsonResponse(
                {
                    "ok": False,
                    "error": "ID de execução inválido.",
                },
                status=400,
            )

        service = AutomationPromptsExecutionService()
        try:
            execution = service.get_execution_status(execution_id=execution_uuid)
        except AutomationPromptsExecutionServiceError as exc:
            return JsonResponse(
                {
                    "ok": False,
                    "error": str(exc),
                },
                status=502,
            )

        integration_source = "api"
        integration_warnings: list[str] = []
        files: list[AutomationExecutionFileItem] = []
        try:
            files = service.list_execution_files(execution_id=execution_uuid)
        except AutomationPromptsExecutionServiceError as exc:
            integration_source = "api_partial"
            integration_warnings = [str(exc)]

        status_meta = _execution_status_meta(execution.status)
        is_terminal = _is_terminal_status(execution.status)
        progress_percent = _resolve_progress_percent(status=execution.status, explicit_progress=execution.progress)
        status_message = _execution_status_message(status=execution.status, error_message=execution.error_message)
        file_rows = _build_file_rows(files)

        return JsonResponse(
            {
                "ok": True,
                "execution_id": str(execution.execution_id),
                "automation_id": str(execution.automation_id),
                "analysis_request_id": str(execution.analysis_request_id),
                "status": execution.status,
                "status_label": status_meta["label"],
                "status_css_class": status_meta["css_class"],
                "status_message": status_message,
                "progress": execution.progress,
                "progress_percent": progress_percent,
                "is_terminal": is_terminal,
                "error_message": execution.error_message,
                "request_file_id": str(execution.request_file_id) if execution.request_file_id else None,
                "request_file_name": execution.request_file_name,
                "created_at": execution.created_at.isoformat() if execution.created_at else None,
                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
                "checked_at": execution.checked_at.isoformat() if execution.checked_at else None,
                "file_rows": _serialize_file_rows(file_rows),
                "integration_source": integration_source,
                "integration_warnings": integration_warnings,
            }
        )


class AutomationExecutionFileDownloadView(LoginRequiredMixin, View):
    def get(self, request, file_id: str):
        try:
            file_uuid = UUID(str(file_id))
        except ValueError:
            messages.error(request, "ID de arquivo inválido para download.")
            return redirect("prompts:list")

        payload = AutomationPromptsExecutionService().download_execution_file(file_id=file_uuid)
        if not payload.get("ok"):
            messages.error(
                request,
                str(payload.get("error") or "Falha ao baixar arquivo remoto da execução."),
            )
            referer = str(request.META.get("HTTP_REFERER") or "").strip()
            if referer:
                return redirect(referer)
            return redirect("prompts:list")

        content = payload.get("content") or b""
        filename = str(payload.get("filename") or f"{file_uuid}.bin")
        content_type = str(payload.get("content_type") or "application/octet-stream")
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        checksum = payload.get("checksum")
        if checksum:
            response["X-File-Checksum"] = str(checksum)
        return response
