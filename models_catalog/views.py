from __future__ import annotations

from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import FormView, ListView

from core.services.provider_models_api_service import (
    ProviderModelReadItem,
    ProviderModelsAPIService,
    ProviderModelsAPIServiceError,
)

from .forms import ProviderModelCreateForm, ProviderModelUpdateForm


def _redirect_legacy_local_route(request, *, local_pk: int) -> object:
    messages.warning(
        request,
        (
            f"Rota legada por ID local ({local_pk}) descontinuada. "
            "Use rotas com ID remoto (UUID) para operar diretamente na FastAPI."
        ),
    )
    return redirect("models_catalog:list")


class ProviderModelListView(LoginRequiredMixin, ListView):
    template_name = "models_catalog/list.html"
    context_object_name = "models"

    def get_queryset(self):
        payload = ProviderModelsAPIService().get_models_list()
        self.models_source = payload["source"]
        self.models_warnings = payload["warnings"]
        return payload["items"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Modelos",
                "page_subtitle": "Catalogo administrativo de modelos de IA.",
                "active_menu": "modelos",
                "integration_source": getattr(self, "models_source", "fallback_local"),
                "integration_warnings": getattr(self, "models_warnings", []),
            }
        )
        return context


class ProviderModelCreateView(LoginRequiredMixin, FormView):
    form_class = ProviderModelCreateForm
    template_name = "models_catalog/form.html"
    success_url = reverse_lazy("models_catalog:list")

    @staticmethod
    def _resolve_selected_provider_id(request) -> str | None:
        provider_value = (
            request.POST.get("provider")
            if request.method == "POST"
            else request.GET.get("provider")
        )
        provider_id = str(provider_value or "").strip()
        return provider_id or None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        selected_provider_id = self._resolve_selected_provider_id(self.request)
        selected_model_key = (
            self.request.POST.get("known_model")
            if self.request.method == "POST"
            else self.request.GET.get("model")
        )

        service = ProviderModelsAPIService()
        provider_choices_payload = service.get_provider_choices()
        kwargs["provider_choices"] = provider_choices_payload["choices"]
        kwargs["catalog_provider_id"] = selected_provider_id
        kwargs["catalog_model_key"] = selected_model_key

        if selected_provider_id:
            try:
                remote_provider_id = UUID(selected_provider_id)
                kwargs["available_models_payload"] = service.get_available_models(
                    remote_provider_id=remote_provider_id
                )
            except ValueError:
                kwargs["available_models_payload"] = {
                    "items": [],
                    "source": "unavailable",
                    "warnings": ["Provider informado é inválido."],
                }
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Novo modelo",
                "form_title": "Novo modelo",
                "form_subtitle": (
                    "Selecione um modelo disponível do provider via FastAPI para manter o catálogo consistente."
                ),
                "active_menu": "modelos",
                "submit_label": "Salvar modelo",
                "is_create_mode": True,
                "available_models_endpoint": reverse_lazy("models_catalog:available_models"),
                "remote_model_id": None,
            }
        )
        return context

    def form_valid(self, form):
        selected_model = form.selected_known_model or {}
        model_name = str(selected_model.get("name") or "").strip()
        model_slug = str(selected_model.get("slug") or "").strip().lower()
        if not model_name or not model_slug:
            form.add_error("known_model", "Modelo selecionado inválido para cadastro remoto.")
            return self.form_invalid(form)

        provider_remote_id_raw = str(form.cleaned_data.get("provider") or "").strip()
        try:
            provider_remote_id = UUID(provider_remote_id_raw)
        except ValueError:
            form.add_error("provider", "Provider remoto inválido.")
            return self.form_invalid(form)

        try:
            ProviderModelsAPIService().create_model(
                remote_provider_id=provider_remote_id,
                model_name=model_name,
                model_slug=model_slug,
                context_window=form.cleaned_data.get("context_window"),
                input_cost_per_1k=form.cleaned_data.get("input_cost_per_1k"),
                output_cost_per_1k=form.cleaned_data.get("output_cost_per_1k"),
                is_active=bool(form.cleaned_data.get("is_active", True)),
            )
        except ProviderModelsAPIServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, "Modelo criado com sucesso.")
        return redirect(self.get_success_url())


class ProviderModelUpdateView(LoginRequiredMixin, FormView):
    form_class = ProviderModelUpdateForm
    template_name = "models_catalog/form.html"
    success_url = reverse_lazy("models_catalog:list")
    model_item: ProviderModelReadItem
    remote_model_id: UUID

    def dispatch(self, request, *args, **kwargs):
        self.remote_model_id = kwargs["remote_id"]
        try:
            self.model_item = ProviderModelsAPIService().get_model(
                remote_model_id=self.remote_model_id
            )
        except ProviderModelsAPIServiceError as exc:
            if exc.code == "provider_model_not_found":
                raise Http404("Modelo remoto não encontrado.") from exc
            messages.error(request, str(exc))
            return redirect("models_catalog:list")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial.update(
            {
                "description": self.model_item.description,
                "context_window": self.model_item.context_window,
                "input_cost_per_1k": self.model_item.input_cost_per_1k,
                "output_cost_per_1k": self.model_item.output_cost_per_1k,
                "is_active": self.model_item.is_active,
            }
        )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Editar modelo",
                "form_title": "Editar modelo",
                "form_subtitle": (
                    "Provider e identificacao do modelo ficam bloqueados para preservar consistencia."
                ),
                "active_menu": "modelos",
                "submit_label": "Salvar alterações",
                "is_create_mode": False,
                "locked_provider_name": self.model_item.provider.name,
                "locked_model_name": self.model_item.name,
                "locked_model_slug": self.model_item.slug,
                "remote_model_id": self.remote_model_id,
            }
        )
        return context

    def form_valid(self, form):
        try:
            ProviderModelsAPIService().update_model(
                remote_model_id=self.remote_model_id,
                context_window=form.cleaned_data.get("context_window"),
                input_cost_per_1k=form.cleaned_data.get("input_cost_per_1k"),
                output_cost_per_1k=form.cleaned_data.get("output_cost_per_1k"),
                is_active=bool(form.cleaned_data.get("is_active", True)),
            )
        except ProviderModelsAPIServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, "Modelo atualizado com sucesso.")
        return redirect(self.get_success_url())


@login_required
def provider_model_edit_legacy(request, pk: int):
    return _redirect_legacy_local_route(request, local_pk=pk)


@login_required
@require_POST
def provider_model_toggle_status(request, remote_id: UUID):
    service = ProviderModelsAPIService()
    try:
        current = service.get_model(remote_model_id=remote_id)
        updated = service.set_model_status(
            remote_model_id=remote_id,
            target_active=not bool(current.is_active),
        )
    except ProviderModelsAPIServiceError as exc:
        messages.error(request, f"Não foi possível sincronizar status do modelo na FastAPI: {exc}")
        return redirect("models_catalog:list")

    if updated.is_active:
        messages.success(request, "Modelo ativado com sucesso.")
    else:
        messages.success(request, "Modelo desativado com sucesso.")

    return redirect("models_catalog:list")


@login_required
@require_POST
def provider_model_toggle_status_legacy(request, pk: int):
    return _redirect_legacy_local_route(request, local_pk=pk)


@login_required
@require_POST
def provider_model_delete(request, remote_id: UUID):
    service = ProviderModelsAPIService()
    model_name = "modelo"
    try:
        current = service.get_model(remote_model_id=remote_id)
        model_name = str(current.name or "").strip() or "modelo"
        service.delete_model(remote_model_id=remote_id)
    except ProviderModelsAPIServiceError as exc:
        messages.error(
            request,
            "Não foi possível excluir o modelo no catálogo remoto da FastAPI: "
            f"{exc}",
        )
        return redirect("models_catalog:list")

    messages.success(request, f'Modelo "{model_name}" excluido com sucesso.')
    return redirect("models_catalog:list")


@login_required
@require_POST
def provider_model_delete_legacy(request, pk: int):
    return _redirect_legacy_local_route(request, local_pk=pk)


@login_required
@require_GET
def provider_available_models(request):
    provider_value = str(request.GET.get("provider") or "").strip()
    try:
        remote_provider_id = UUID(provider_value)
    except ValueError:
        return JsonResponse(
            {
                "items": [],
                "source": "unavailable",
                "warnings": ["Provider informado é inválido."],
                "provider_remote_id": None,
            },
            status=400,
        )

    payload = ProviderModelsAPIService().get_available_models(
        remote_provider_id=remote_provider_id
    )
    return JsonResponse(payload, status=200)
