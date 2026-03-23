from __future__ import annotations

import json
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.text import slugify
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from core.services.automation_prompts_execution_service import (
    AutomationPromptsExecutionService,
    AutomationPromptsExecutionServiceError,
    OfficialOwnerTokenReadItem,
    ProviderCredentialReadItem,
    ProviderModelReadItem,
    ProviderReadItem,
)
from test_prompts.models import TestPrompt

from .forms import TestAutomationCopyToOfficialForm, TestAutomationForm
from .models import TestAutomation
from .output_contract import (
    label_output_type,
    label_result_formatter,
    label_result_parser,
    summarize_output_schema,
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


def _load_owner_token_options() -> tuple[list[OfficialOwnerTokenReadItem], list[str]]:
    service = AutomationPromptsExecutionService()
    try:
        return service.list_official_owner_tokens(), []
    except AutomationPromptsExecutionServiceError as exc:
        return [], [str(exc)]


def _load_linked_test_prompt(automation_id: UUID) -> TestPrompt | None:
    return (
        TestPrompt.objects.filter(automation_id=automation_id)
        .exclude(prompt_text__isnull=True)
        .exclude(prompt_text__exact="")
        .order_by("-is_active", "-updated_at", "-id")
        .first()
    )


def _resolve_uuid(raw_value: str | UUID | None) -> UUID | None:
    raw = str(raw_value or "").strip()
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def _build_unique_slug(*, name: str, current_id: UUID | None = None) -> str:
    base_slug = slugify(name) or "automacao-teste"
    candidate = base_slug
    sequence = 2
    queryset = TestAutomation.objects.all()
    if current_id is not None:
        queryset = queryset.exclude(pk=current_id)
    while queryset.filter(slug=candidate).exists():
        candidate = f"{base_slug}-{sequence}"
        sequence += 1
    return candidate


def _serialize_output_schema_for_form(output_schema: dict | str | None) -> str:
    if output_schema is None:
        return ""
    if isinstance(output_schema, str):
        return output_schema
    if isinstance(output_schema, dict):
        return json.dumps(output_schema, ensure_ascii=False, indent=2)
    return ""


def _decorate_output_contract_display(item: TestAutomation) -> None:
    item.output_type_label = label_output_type(item.output_type)
    item.result_parser_label = label_result_parser(item.result_parser)
    item.result_formatter_label = label_result_formatter(item.result_formatter)
    item.output_schema_summary_label = summarize_output_schema(item.output_schema)
    item.output_contract_source_label = (
        "Contrato explicito" if item.has_explicit_output_contract else "Padrao legado"
    )
    item.output_contract_source_css = (
        "status-success" if item.has_explicit_output_contract else "status-neutral"
    )
    item.debug_mode_label = "Ativo" if bool(getattr(item, "debug_enabled", False)) else "Desativado"
    item.debug_mode_css = "status-warning" if bool(getattr(item, "debug_enabled", False)) else "status-neutral"


class TestAutomationListView(LoginRequiredMixin, ListView):
    template_name = "test_automations/list.html"
    context_object_name = "test_automations"
    model = TestAutomation

    def get_queryset(self):
        queryset = TestAutomation.objects.all().order_by("-updated_at", "name")
        search_query = str(self.request.GET.get("q") or "").strip()
        selected_status = str(self.request.GET.get("status") or "").strip().lower()

        if search_query:
            queryset = queryset.filter(name__icontains=search_query)
        if selected_status == "ativo":
            queryset = queryset.filter(is_active=True)
        elif selected_status == "inativo":
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items = context.get("test_automations") or []
        for item in items:
            _decorate_output_contract_display(item)
        context.update(
            {
                "page_title": "Automações de teste",
                "page_subtitle": "CRUD local das automações de teste usadas na execução experimental.",
                "active_menu": "automacoes_teste",
                "integration_source": "local",
                "integration_warnings": [],
                "search_query": str(self.request.GET.get("q") or "").strip(),
                "selected_status": str(self.request.GET.get("status") or "").strip().lower(),
                "total_count": TestAutomation.objects.count(),
                "filtered_count": len(items),
                "list_counter_label": f"{len(items)} automação(ões) de teste",
            }
        )
        return context


class _BaseTestAutomationFormView(LoginRequiredMixin, FormView):
    form_class = TestAutomationForm
    automation: TestAutomation | None = None

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

        selected_provider = self._resolve_selected_provider_id(
            fallback=self.automation.provider_id if self.automation is not None else None
        )
        selected_model = (
            _resolve_uuid(self.request.POST.get("model_id"))
            if self.request.method.upper() == "POST"
            else None
        ) or (self.automation.model_id if self.automation is not None else None)
        selected_credential = (
            _resolve_uuid(self.request.POST.get("credential_id"))
            if self.request.method.upper() == "POST"
            else None
        ) or (self.automation.credential_id if self.automation is not None else None)
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
            else _serialize_output_schema_for_form(
                getattr(self.automation, "output_schema", None) if self.automation is not None else None
            )
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
            self.automation is not None
            and self.automation.provider_id == selected_provider
            and all(str(self.automation.model_id) != value for value, _ in model_choices)
        ):
            model_choices.append(
                (
                    str(self.automation.model_id),
                    f"{self.automation.model_slug} ({self.automation.model_id})",
                )
            )
        if (
            self.automation is not None
            and self.automation.credential_id is not None
            and self.automation.provider_id == selected_provider
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

    def _resolve_runtime_snapshot(
        self,
        *,
        provider_id: UUID,
        model_id: UUID,
        credential_id: UUID | None,
    ) -> tuple[ProviderReadItem, ProviderModelReadItem, ProviderCredentialReadItem | None] | None:
        provider_options, _, provider_warnings = _load_provider_options()
        provider = next((item for item in provider_options if item.id == provider_id), None)
        if provider is None:
            return None

        provider_models, model_warnings = _load_provider_models(provider_id)
        provider_credentials, credential_warnings = _load_provider_credentials(provider_id)
        self.integration_warnings = [*provider_warnings, *model_warnings, *credential_warnings]
        self.integration_source = "api" if not self.integration_warnings else "api_catalog"

        model = next((item for item in provider_models if item.id == model_id), None)
        if model is None:
            return None

        credential = None
        if credential_id is not None:
            credential = next((item for item in provider_credentials if item.id == credential_id), None)
            if credential is None:
                return None
        return provider, model, credential

    @staticmethod
    def _resolve_runtime_ids(form) -> tuple[UUID, UUID, UUID | None] | None:
        provider_id = _resolve_uuid(form.cleaned_data.get("provider_id"))
        model_id = _resolve_uuid(form.cleaned_data.get("model_id"))
        credential_id = _resolve_uuid(form.cleaned_data.get("credential_id"))
        if provider_id is None or model_id is None:
            return None
        return provider_id, model_id, credential_id

    @staticmethod
    def _resolve_output_contract_payload(form) -> tuple[str, str, str, dict | None]:
        return (
            str(form.cleaned_data.get("output_type") or "").strip(),
            str(form.cleaned_data.get("result_parser") or "").strip(),
            str(form.cleaned_data.get("result_formatter") or "").strip(),
            form.cleaned_data.get("output_schema_parsed"),
        )


class TestAutomationCreateView(_BaseTestAutomationFormView):
    template_name = "test_automations/form.html"
    success_url = reverse_lazy("test_automations:list")

    def get_form_kwargs(self):
        return self._build_form_kwargs()

    def form_valid(self, form):
        parsed = self._resolve_runtime_ids(form)
        if parsed is None:
            form.add_error(None, "Provider/model inválidos.")
            return self.form_invalid(form)
        provider_id, model_id, credential_id = parsed

        snapshot = self._resolve_runtime_snapshot(
            provider_id=provider_id,
            model_id=model_id,
            credential_id=credential_id,
        )
        if snapshot is None:
            form.add_error(None, "Não foi possível validar provider, modelo e credencial selecionados.")
            return self.form_invalid(form)
        provider, model, credential = snapshot
        output_type, result_parser, result_formatter, output_schema = self._resolve_output_contract_payload(form)

        automation = TestAutomation.objects.create(
            name=form.cleaned_data["name"],
            slug=_build_unique_slug(name=form.cleaned_data["name"]),
            provider_id=provider.id,
            model_id=model.id,
            credential_id=credential.id if credential is not None else None,
            provider_slug=provider.slug,
            model_slug=model.model_slug,
            credential_name=credential.credential_name if credential is not None else "",
            output_type=output_type,
            result_parser=result_parser,
            result_formatter=result_formatter,
            output_schema=output_schema,
            debug_enabled=bool(form.cleaned_data.get("debug_enabled", False)),
            is_active=bool(form.cleaned_data.get("is_active", False)),
            created_by=self.request.user if self.request.user.is_authenticated else None,
            updated_by=self.request.user if self.request.user.is_authenticated else None,
        )
        messages.success(self.request, "Automação de teste criada com sucesso.")
        return redirect("test_automations:detail", automation_id=automation.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Nova automação de teste",
                "form_title": "Nova automação de teste",
                "form_subtitle": "Cadastro local da automação de teste, sem criar entidades técnicas na API.",
                "active_menu": "automacoes_teste",
                "submit_label": "Salvar automação de teste",
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
                "provider_models_url": reverse("test_automations:provider_models"),
                "provider_credentials_url": reverse("test_automations:provider_credentials"),
                "is_editing": False,
                "object": None,
            }
        )
        return context


class TestAutomationDetailView(LoginRequiredMixin, TemplateView):
    template_name = "test_automations/detail.html"
    automation: TestAutomation

    def dispatch(self, request, *args, **kwargs):
        try:
            self.automation = TestAutomation.objects.get(pk=kwargs["automation_id"])
        except TestAutomation.DoesNotExist as exc:
            raise Http404("Automação de teste não encontrada.") from exc
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        _decorate_output_contract_display(self.automation)
        context.update(
            {
                "page_title": self.automation.name,
                "active_menu": "automacoes_teste",
                "automation": self.automation,
                "integration_source": "local",
                "integration_warnings": [],
            }
        )
        return context


class TestAutomationCopyToOfficialView(LoginRequiredMixin, FormView):
    template_name = "test_automations/copy_to_official.html"
    form_class = TestAutomationCopyToOfficialForm
    automation: TestAutomation
    source_prompt: TestPrompt | None = None

    def dispatch(self, request, *args, **kwargs):
        try:
            self.automation = TestAutomation.objects.get(pk=kwargs["automation_id"])
        except TestAutomation.DoesNotExist as exc:
            raise Http404("AutomaÃ§Ã£o de teste nÃ£o encontrada.") from exc
        self.source_prompt = _load_linked_test_prompt(self.automation.id)
        if self.source_prompt is None:
            messages.error(
                request,
                "A cÃ³pia para oficial exige prompt de teste vinculado. Cadastre um prompt antes de continuar.",
            )
            return redirect("test_automations:detail", automation_id=self.automation.id)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        owner_tokens, warnings = _load_owner_token_options()
        self.integration_warnings = list(warnings)
        owner_token_choices = [(str(item.id), f"{item.name} ({item.id})") for item in owner_tokens]
        selected_owner = (
            str(self.request.POST.get("owner_token_id") or "").strip()
            if self.request.method.upper() == "POST"
            else ""
        )
        if selected_owner and all(choice_value != selected_owner for choice_value, _ in owner_token_choices):
            owner_token_choices.append((selected_owner, selected_owner))
        kwargs["owner_token_choices"] = owner_token_choices
        return kwargs

    def form_valid(self, form):
        owner_token_id = _resolve_uuid(form.cleaned_data.get("owner_token_id"))
        if owner_token_id is None:
            form.add_error("owner_token_id", "Token oficial de destino invÃ¡lido.")
            return self.form_invalid(form)

        source_prompt = self.source_prompt or _load_linked_test_prompt(self.automation.id)
        if source_prompt is None:
            form.add_error(None, "NÃ£o existe prompt vinculado para copiar.")
            return self.form_invalid(form)
        prompt_text = str(source_prompt.prompt_text or "").strip()
        if not prompt_text:
            form.add_error(None, "O prompt vinculado estÃ¡ vazio. Ajuste o prompt antes de copiar para oficial.")
            return self.form_invalid(form)

        service = AutomationPromptsExecutionService()
        try:
            result = service.copy_test_automation_to_official(
                owner_token_id=owner_token_id,
                name=self.automation.name,
                provider_id=self.automation.provider_id,
                model_id=self.automation.model_id,
                credential_id=self.automation.credential_id,
                output_type=str(self.automation.output_type or "").strip() or None,
                result_parser=str(self.automation.result_parser or "").strip() or None,
                result_formatter=str(self.automation.result_formatter or "").strip() or None,
                output_schema=(
                    self.automation.output_schema
                    if isinstance(self.automation.output_schema, dict)
                    else None
                ),
                is_active=bool(self.automation.is_active),
                prompt_text=prompt_text,
                source_test_automation_id=self.automation.id,
                source_test_prompt_id=source_prompt.id,
            )
        except AutomationPromptsExecutionServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(
            self.request,
            (
                "AutomaÃ§Ã£o copiada para oficial com sucesso. "
                f"Automation oficial: {result.automation_id} | Prompt oficial: {result.prompt_id}."
            ),
        )
        return redirect("test_automations:detail", automation_id=self.automation.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        _decorate_output_contract_display(self.automation)
        context.update(
            {
                "page_title": "Copiar para oficial",
                "active_menu": "automacoes_teste",
                "automation": self.automation,
                "linked_prompt": self.source_prompt,
                "integration_source": "api",
                "integration_warnings": getattr(self, "integration_warnings", []),
            }
        )
        return context


class TestAutomationUpdateView(_BaseTestAutomationFormView):
    template_name = "test_automations/form.html"

    def dispatch(self, request, *args, **kwargs):
        try:
            self.automation = TestAutomation.objects.get(pk=kwargs["automation_id"])
        except TestAutomation.DoesNotExist as exc:
            raise Http404("Automação de teste não encontrada.") from exc
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {
            "name": self.automation.name,
            "provider_id": str(self.automation.provider_id),
            "model_id": str(self.automation.model_id),
            "credential_id": str(self.automation.credential_id or ""),
            "output_type": str(self.automation.output_type or ""),
            "result_parser": str(self.automation.result_parser or ""),
            "result_formatter": str(self.automation.result_formatter or ""),
            "output_schema": _serialize_output_schema_for_form(self.automation.output_schema),
            "debug_enabled": bool(self.automation.debug_enabled),
            "is_active": self.automation.is_active,
        }

    def get_form_kwargs(self):
        return self._build_form_kwargs()

    def form_valid(self, form):
        parsed = self._resolve_runtime_ids(form)
        if parsed is None:
            form.add_error(None, "Provider/model inválidos.")
            return self.form_invalid(form)
        provider_id, model_id, credential_id = parsed

        snapshot = self._resolve_runtime_snapshot(
            provider_id=provider_id,
            model_id=model_id,
            credential_id=credential_id,
        )
        if snapshot is None:
            form.add_error(None, "Não foi possível validar provider, modelo e credencial selecionados.")
            return self.form_invalid(form)
        provider, model, credential = snapshot
        output_type, result_parser, result_formatter, output_schema = self._resolve_output_contract_payload(form)

        self.automation.name = form.cleaned_data["name"]
        self.automation.slug = _build_unique_slug(name=form.cleaned_data["name"], current_id=self.automation.id)
        self.automation.provider_id = provider.id
        self.automation.model_id = model.id
        self.automation.credential_id = credential.id if credential is not None else None
        self.automation.provider_slug = provider.slug
        self.automation.model_slug = model.model_slug
        self.automation.credential_name = credential.credential_name if credential is not None else ""
        self.automation.output_type = output_type
        self.automation.result_parser = result_parser
        self.automation.result_formatter = result_formatter
        self.automation.output_schema = output_schema
        self.automation.debug_enabled = bool(form.cleaned_data.get("debug_enabled", False))
        self.automation.is_active = bool(form.cleaned_data.get("is_active", False))
        self.automation.updated_by = self.request.user if self.request.user.is_authenticated else None
        self.automation.save()

        messages.success(self.request, "Automação de teste atualizada com sucesso.")
        return redirect("test_automations:detail", automation_id=self.automation.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Editar automação de teste",
                "form_title": "Editar automação de teste",
                "form_subtitle": "A automação continua local; a API só fornece catálogo e engine.",
                "active_menu": "automacoes_teste",
                "submit_label": "Salvar alterações",
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
                "provider_models_url": reverse("test_automations:provider_models"),
                "provider_credentials_url": reverse("test_automations:provider_credentials"),
                "is_editing": True,
                "object": self.automation,
            }
        )
        return context


class TestAutomationDeleteView(LoginRequiredMixin, TemplateView):
    template_name = "test_automations/delete.html"
    automation: TestAutomation

    def dispatch(self, request, *args, **kwargs):
        try:
            self.automation = TestAutomation.objects.get(pk=kwargs["automation_id"])
        except TestAutomation.DoesNotExist as exc:
            raise Http404("Automação de teste não encontrada.") from exc
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        automation_name = self.automation.name
        self.automation.delete()
        messages.success(request, f'Automação de teste "{automation_name}" excluída com sucesso.')
        return redirect("test_automations:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Excluir automação de teste",
                "active_menu": "automacoes_teste",
                "automation": self.automation,
            }
        )
        return context


class TestAutomationProviderModelsView(LoginRequiredMixin, View):
    def get(self, request):
        provider_id = _resolve_uuid(request.GET.get("provider_id"))
        if provider_id is None:
            return JsonResponse({"ok": False, "error": "Provider inválido.", "items": []}, status=400)

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


class TestAutomationProviderCredentialsView(LoginRequiredMixin, View):
    def get(self, request):
        provider_id = _resolve_uuid(request.GET.get("provider_id"))
        if provider_id is None:
            return JsonResponse({"ok": False, "error": "Provider inválido.", "items": []}, status=400)

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
