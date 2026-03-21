from __future__ import annotations

from uuid import UUID

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from core.services.automation_prompts_execution_service import (
    AutomationPromptsExecutionService,
    AutomationPromptsExecutionServiceError,
    ProviderModelReadItem,
    ProviderReadItem,
    TestAutomationReadItem,
)

from .forms import TestAutomationForm


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


class TestAutomationListView(LoginRequiredMixin, ListView):
    template_name = "test_automations/list.html"
    context_object_name = "test_automations"

    def get_queryset(self):
        service = AutomationPromptsExecutionService()
        try:
            items = service.list_test_automations(active_only=False)
            self.integration_source = "api"
            self.integration_warnings = []
        except AutomationPromptsExecutionServiceError as exc:
            items = []
            self.integration_source = "unavailable"
            self.integration_warnings = [str(exc)]

        search_query = str(self.request.GET.get("q") or "").strip().lower()
        selected_status = str(self.request.GET.get("status") or "").strip().lower()

        filtered: list[TestAutomationReadItem] = []
        for item in items:
            if search_query and search_query not in str(item.automation_name).lower():
                continue
            if selected_status == "ativo" and not item.is_active:
                continue
            if selected_status == "inativo" and item.is_active:
                continue
            filtered.append(item)
        return filtered

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items = context.get("test_automations") or []
        context.update(
            {
                "page_title": "Automações de teste",
                "page_subtitle": "Gestão separada de automações de teste, independente dos prompts de teste.",
                "active_menu": "automacoes_teste",
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
                "search_query": str(self.request.GET.get("q") or "").strip(),
                "selected_status": str(self.request.GET.get("status") or "").strip().lower(),
                "total_count": len(items),
                "list_counter_label": f"{len(items)} automacao(oes) de teste",
            }
        )
        return context


class _BaseTestAutomationFormView(LoginRequiredMixin, FormView):
    form_class = TestAutomationForm

    def _resolve_selected_provider_id(self, *, fallback: UUID | None = None) -> UUID | None:
        raw = str(
            self.request.POST.get("provider_id")
            if self.request.method.upper() == "POST"
            else self.request.GET.get("provider_id")
            or fallback
            or ""
        ).strip()
        if not raw:
            return None
        try:
            return UUID(raw)
        except ValueError:
            return None

    def _build_form_kwargs(
        self,
        *,
        selected_provider_fallback: UUID | None = None,
        selected_model_fallback: UUID | None = None,
    ) -> dict:
        kwargs = super().get_form_kwargs()
        provider_options, provider_source, provider_warnings = _load_provider_options()
        self.integration_source = provider_source
        self.integration_warnings = provider_warnings

        provider_choices = [(str(item.id), f"{item.name} ({item.slug})") for item in provider_options]
        selected_provider = self._resolve_selected_provider_id(fallback=selected_provider_fallback)
        model_choices: list[tuple[str, str]] = []
        if selected_provider is not None:
            provider_models, model_warnings = _load_provider_models(selected_provider)
            self.integration_warnings.extend(model_warnings)
            model_choices = [
                (str(item.id), f"{item.model_name} ({item.model_slug})")
                for item in provider_models
            ]
        kwargs["provider_choices"] = provider_choices
        kwargs["model_choices"] = model_choices
        kwargs["selected_provider"] = str(selected_provider) if selected_provider is not None else None
        kwargs["selected_model"] = str(selected_model_fallback) if selected_model_fallback is not None else None
        return kwargs

    @staticmethod
    def _parse_provider_model(form) -> tuple[UUID, UUID] | None:
        try:
            return UUID(str(form.cleaned_data["provider_id"])), UUID(str(form.cleaned_data["model_id"]))
        except ValueError:
            return None


class TestAutomationCreateView(_BaseTestAutomationFormView):
    template_name = "test_automations/form.html"
    success_url = reverse_lazy("test_automations:list")

    def get_form_kwargs(self):
        return self._build_form_kwargs()

    def form_valid(self, form):
        parsed = self._parse_provider_model(form)
        if parsed is None:
            form.add_error(None, "Provider/model invalido.")
            return self.form_invalid(form)
        provider_id, model_id = parsed

        service = AutomationPromptsExecutionService()
        try:
            service.create_test_automation(
                name=form.cleaned_data["name"],
                provider_id=provider_id,
                model_id=model_id,
            )
        except AutomationPromptsExecutionServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, "Automacao de teste criada com sucesso.")
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Nova automação de teste",
                "form_title": "Nova automação de teste",
                "form_subtitle": "Cadastre a automação de teste em uma área própria, separada dos prompts.",
                "active_menu": "automacoes_teste",
                "submit_label": "Salvar automação de teste",
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
                "provider_models_url": reverse("test_automations:provider_models"),
                "is_editing": False,
                "object": None,
            }
        )
        return context


class TestAutomationDetailView(LoginRequiredMixin, TemplateView):
    template_name = "test_automations/detail.html"
    automation_item: TestAutomationReadItem

    def dispatch(self, request, *args, **kwargs):
        service = AutomationPromptsExecutionService()
        try:
            self.automation_item = service.get_test_automation(automation_id=kwargs["automation_id"])
            self.integration_source = "api"
            self.integration_warnings = []
        except AutomationPromptsExecutionServiceError as exc:
            if exc.code == "test_automation_not_found":
                raise Http404("Automacao de teste nao encontrada.") from exc
            messages.error(request, str(exc))
            return redirect("test_automations:list")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": self.automation_item.automation_name,
                "active_menu": "automacoes_teste",
                "automation": self.automation_item,
                "integration_source": getattr(self, "integration_source", "api"),
                "integration_warnings": getattr(self, "integration_warnings", []),
            }
        )
        return context


class TestAutomationUpdateView(_BaseTestAutomationFormView):
    template_name = "test_automations/form.html"
    success_url = reverse_lazy("test_automations:list")
    automation_item: TestAutomationReadItem

    def dispatch(self, request, *args, **kwargs):
        service = AutomationPromptsExecutionService()
        try:
            self.automation_item = service.get_test_automation(automation_id=kwargs["automation_id"])
        except AutomationPromptsExecutionServiceError as exc:
            if exc.code == "test_automation_not_found":
                raise Http404("Automacao de teste nao encontrada.") from exc
            messages.error(request, str(exc))
            return redirect("test_automations:list")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {
            "name": self.automation_item.automation_name,
            "provider_id": str(self.automation_item.provider_id or ""),
            "model_id": str(self.automation_item.model_id or ""),
            "is_active": self.automation_item.is_active,
        }

    def get_form_kwargs(self):
        return self._build_form_kwargs(
            selected_provider_fallback=self.automation_item.provider_id,
            selected_model_fallback=self.automation_item.model_id,
        )

    def form_valid(self, form):
        parsed = self._parse_provider_model(form)
        if parsed is None:
            form.add_error(None, "Provider/model invalido.")
            return self.form_invalid(form)
        provider_id, model_id = parsed

        service = AutomationPromptsExecutionService()
        try:
            service.update_test_automation(
                automation_id=self.automation_item.automation_id,
                name=form.cleaned_data["name"],
                provider_id=provider_id,
                model_id=model_id,
                is_active=bool(form.cleaned_data.get("is_active", False)),
            )
        except AutomationPromptsExecutionServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, "Automacao de teste atualizada com sucesso.")
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Editar automação de teste",
                "form_title": "Editar automação de teste",
                "form_subtitle": "Altere a automação de teste sem misturar a gestão de prompts.",
                "active_menu": "automacoes_teste",
                "submit_label": "Salvar alteracoes",
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
                "provider_models_url": reverse("test_automations:provider_models"),
                "is_editing": True,
                "object": self.automation_item,
            }
        )
        return context


class TestAutomationDeleteView(LoginRequiredMixin, TemplateView):
    template_name = "test_automations/delete.html"
    automation_item: TestAutomationReadItem

    def dispatch(self, request, *args, **kwargs):
        service = AutomationPromptsExecutionService()
        try:
            self.automation_item = service.get_test_automation(automation_id=kwargs["automation_id"])
        except AutomationPromptsExecutionServiceError as exc:
            if exc.code == "test_automation_not_found":
                raise Http404("Automacao de teste nao encontrada.") from exc
            messages.error(request, str(exc))
            return redirect("test_automations:list")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        service = AutomationPromptsExecutionService()
        try:
            service.delete_test_automation(automation_id=self.automation_item.automation_id)
        except AutomationPromptsExecutionServiceError as exc:
            messages.error(request, str(exc))
            return redirect("test_automations:detail", automation_id=self.automation_item.automation_id)
        messages.success(request, "Automacao de teste excluida com sucesso.")
        return redirect("test_automations:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Excluir automação de teste",
                "active_menu": "automacoes_teste",
                "automation": self.automation_item,
            }
        )
        return context


class TestAutomationProviderModelsView(LoginRequiredMixin, View):
    def get(self, request):
        provider_id_raw = str(request.GET.get("provider_id") or "").strip()
        try:
            provider_id = UUID(provider_id_raw)
        except ValueError:
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
