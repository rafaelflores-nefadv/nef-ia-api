from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

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
        context.update(
            {
                "page_title": "Credenciais",
                "page_subtitle": "Gestão administrativa de credenciais por provider.",
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
        context.update(
            {
                "page_title": "Editar credencial",
                "form_title": "Editar credencial",
                "form_subtitle": "Atualize os dados da credencial selecionada.",
                "active_menu": "credenciais",
                "submit_label": "Salvar alterações",
                "is_editing": True,
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
