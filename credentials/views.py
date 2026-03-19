from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from core.services.provider_connectivity_service import ProviderConnectivityClientService

from .forms import ProviderCredentialForm
from .models import ProviderCredential


class ProviderCredentialListView(LoginRequiredMixin, ListView):
    model = ProviderCredential
    template_name = "credentials/list.html"
    context_object_name = "credentials"

    def get_queryset(self):
        return (
            ProviderCredential.objects.select_related("provider")
            .all()
            .order_by("provider__name", "name")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connectivity_results = self.request.session.get("provider_connectivity_results", {})
        credentials = context.get("credentials")
        if credentials is not None:
            for credential in credentials:
                credential.connectivity_result = connectivity_results.get(str(credential.provider_id))
        context.update(
            {
                "page_title": "Credenciais",
                "page_subtitle": "Gestao administrativa de credenciais por provider.",
                "active_menu": "credenciais",
            }
        )
        return context


class ProviderCredentialCreateView(LoginRequiredMixin, CreateView):
    model = ProviderCredential
    form_class = ProviderCredentialForm
    template_name = "credentials/form.html"
    success_url = reverse_lazy("credentials:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Nova credencial",
                "form_title": "Nova credencial",
                "form_subtitle": "Cadastre uma credencial vinculada a um provider.",
                "active_menu": "credenciais",
                "submit_label": "Salvar credencial",
                "is_editing": False,
            }
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Credencial criada com sucesso.")
        return response


class ProviderCredentialUpdateView(LoginRequiredMixin, UpdateView):
    model = ProviderCredential
    form_class = ProviderCredentialForm
    template_name = "credentials/form.html"
    success_url = reverse_lazy("credentials:list")

    def get_queryset(self):
        return ProviderCredential.objects.select_related("provider")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connectivity_results = self.request.session.get("provider_connectivity_results", {})
        latest_result = connectivity_results.get(str(self.object.provider_id))
        context.update(
            {
                "page_title": "Editar credencial",
                "form_title": "Editar credencial",
                "form_subtitle": "Atualize os dados da credencial selecionada.",
                "active_menu": "credenciais",
                "submit_label": "Salvar alteracoes",
                "is_editing": True,
                "latest_connectivity_result": latest_result,
            }
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Credencial atualizada com sucesso.")
        return response


@login_required
@require_POST
def provider_credential_toggle_status(request, pk: int):
    credential = get_object_or_404(ProviderCredential, pk=pk)
    credential.is_active = not credential.is_active
    credential.save(update_fields=["is_active", "updated_at"])

    if credential.is_active:
        messages.success(request, "Credencial ativada com sucesso.")
    else:
        messages.success(request, "Credencial desativada com sucesso.")

    return redirect("credentials:list")


def _store_connectivity_result(request, *, provider_id: int, result: dict) -> None:
    cache = request.session.get("provider_connectivity_results", {})
    cache[str(provider_id)] = {
        "ok": bool(result.get("ok")),
        "status": str(result.get("status") or ""),
        "status_label": str(result.get("status_label") or ""),
        "message": str(result.get("message") or ""),
        "error_code": str(result.get("error_code") or ""),
    }
    request.session["provider_connectivity_results"] = cache


def _publish_connectivity_message(request, *, result: dict) -> None:
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


@login_required
@require_POST
def provider_credential_test_connectivity(request, pk: int):
    credential = get_object_or_404(ProviderCredential.objects.select_related("provider"), pk=pk)
    provider = credential.provider
    result = ProviderConnectivityClientService().test_provider_connectivity(provider=provider)

    _store_connectivity_result(request, provider_id=provider.id, result=result)
    _publish_connectivity_message(request, result=result)

    next_url = str(request.POST.get("next") or "").strip()
    if next_url:
        return redirect(next_url)
    return redirect("credentials:list")
