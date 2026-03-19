from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from core.services.provider_connectivity_service import ProviderConnectivityClientService
from core.services.provider_models_service import ProviderModelsService, ProviderModelsServiceError

from .forms import ProviderForm
from .models import Provider


def _store_provider_connectivity_result(request, *, provider_id: int, result: dict) -> None:
    cache = request.session.get("provider_connectivity_results", {})
    cache[str(provider_id)] = {
        "ok": bool(result.get("ok")),
        "status": str(result.get("status") or ""),
        "status_label": str(result.get("status_label") or ""),
        "message": str(result.get("message") or ""),
        "error_code": str(result.get("error_code") or ""),
    }
    request.session["provider_connectivity_results"] = cache


def _publish_provider_connectivity_message(request, *, result: dict) -> None:
    ok = bool(result.get("ok"))
    status = str(result.get("status") or "").strip()
    status_label = str(result.get("status_label") or "").strip() or "Status"
    message = str(result.get("message") or "").strip() or "Teste concluido."
    full_message = f"{status_label}: {message}"

    if ok:
        messages.success(request, full_message)
        return

    warning_statuses = {
        "provider_not_synced",
        "provider_inactive",
        "credential_not_found",
        "credential_inactive",
        "provider_not_supported",
    }
    if status in warning_statuses:
        messages.warning(request, full_message)
        return

    messages.error(request, full_message)


class ProviderListView(LoginRequiredMixin, ListView):
    model = Provider
    template_name = "providers/list.html"
    context_object_name = "providers"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connectivity_results = self.request.session.get("provider_connectivity_results", {})
        providers = context.get("providers")
        if providers is not None:
            for provider in providers:
                provider.connectivity_result = connectivity_results.get(str(provider.id))
        context.update(
            {
                "page_title": "Providers",
                "page_subtitle": "Gestao administrativa de integracoes disponiveis.",
                "active_menu": "providers",
            }
        )
        return context


class ProviderCreateView(LoginRequiredMixin, CreateView):
    model = Provider
    form_class = ProviderForm
    template_name = "providers/form.html"
    success_url = reverse_lazy("providers:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Novo provider",
                "form_title": "Novo provider",
                "form_subtitle": "Cadastre um novo provider para a plataforma.",
                "active_menu": "providers",
                "submit_label": "Salvar provider",
                "is_editing": False,
            }
        )
        return context

    def form_valid(self, form):
        candidate = form.save(commit=False)
        try:
            remote_provider_id = ProviderModelsService().sync_provider(provider=candidate)
        except ProviderModelsServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        form.instance.fastapi_provider_id = remote_provider_id
        response = super().form_valid(form)
        messages.success(self.request, "Provider criado com sucesso.")
        return response


class ProviderUpdateView(LoginRequiredMixin, UpdateView):
    model = Provider
    form_class = ProviderForm
    template_name = "providers/form.html"
    success_url = reverse_lazy("providers:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connectivity_results = self.request.session.get("provider_connectivity_results", {})
        latest_result = connectivity_results.get(str(self.object.id))
        context.update(
            {
                "page_title": "Editar provider",
                "form_title": "Editar provider",
                "form_subtitle": "Atualize os dados do provider selecionado.",
                "active_menu": "providers",
                "submit_label": "Salvar alteracoes",
                "is_editing": True,
                "latest_connectivity_result": latest_result,
            }
        )
        return context

    def form_valid(self, form):
        candidate = form.save(commit=False)
        try:
            remote_provider_id = ProviderModelsService().sync_provider(provider=candidate)
        except ProviderModelsServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        form.instance.fastapi_provider_id = remote_provider_id
        response = super().form_valid(form)
        messages.success(self.request, "Provider atualizado com sucesso.")
        return response


@login_required
@require_POST
def provider_toggle_status(request, pk: int):
    provider = get_object_or_404(Provider, pk=pk)
    previous_status = bool(provider.is_active)
    provider.is_active = not previous_status
    try:
        remote_provider_id = ProviderModelsService().sync_provider(provider=provider)
    except ProviderModelsServiceError as exc:
        provider.is_active = previous_status
        messages.error(
            request,
            f"Nao foi possivel sincronizar status do provider na FastAPI: {exc}",
        )
        return redirect("providers:list")

    provider.fastapi_provider_id = remote_provider_id
    provider.save(update_fields=["is_active", "fastapi_provider_id", "updated_at"])

    if provider.is_active:
        messages.success(request, "Provider ativado com sucesso.")
    else:
        messages.success(request, "Provider desativado com sucesso.")

    return redirect("providers:list")


@login_required
@require_POST
def provider_test_connectivity(request, pk: int):
    provider = get_object_or_404(Provider, pk=pk)
    result = ProviderConnectivityClientService().test_provider_connectivity(provider=provider)
    _store_provider_connectivity_result(request, provider_id=provider.id, result=result)
    _publish_provider_connectivity_message(request, result=result)

    next_url = str(request.POST.get("next") or "").strip()
    if next_url:
        return redirect(next_url)
    return redirect("providers:list")
