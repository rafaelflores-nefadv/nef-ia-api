from __future__ import annotations

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
    ProviderCredentialReadItem,
    ProviderModelReadItem,
    ProviderReadItem,
)

from .forms import TestAutomationForm
from .models import TestAutomation


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

        automation = TestAutomation.objects.create(
            name=form.cleaned_data["name"],
            slug=_build_unique_slug(name=form.cleaned_data["name"]),
            provider_id=provider.id,
            model_id=model.id,
            credential_id=credential.id if credential is not None else None,
            provider_slug=provider.slug,
            model_slug=model.model_slug,
            credential_name=credential.credential_name if credential is not None else "",
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

        self.automation.name = form.cleaned_data["name"]
        self.automation.slug = _build_unique_slug(name=form.cleaned_data["name"], current_id=self.automation.id)
        self.automation.provider_id = provider.id
        self.automation.model_id = model.id
        self.automation.credential_id = credential.id if credential is not None else None
        self.automation.provider_slug = provider.slug
        self.automation.model_slug = model.model_slug
        self.automation.credential_name = credential.credential_name if credential is not None else ""
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
