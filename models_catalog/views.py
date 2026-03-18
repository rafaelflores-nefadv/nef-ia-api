from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from .forms import ProviderModelForm
from .models import ProviderModel


class ProviderModelListView(LoginRequiredMixin, ListView):
    model = ProviderModel
    template_name = "models_catalog/list.html"
    context_object_name = "models"

    def get_queryset(self):
        return (
            ProviderModel.objects.select_related("provider")
            .all()
            .order_by("provider__name", "name")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Modelos",
                "page_subtitle": "Catálogo administrativo de modelos de IA.",
                "active_menu": "modelos",
            }
        )
        return context


class ProviderModelCreateView(LoginRequiredMixin, CreateView):
    model = ProviderModel
    form_class = ProviderModelForm
    template_name = "models_catalog/form.html"
    success_url = reverse_lazy("models_catalog:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Novo modelo",
                "form_title": "Novo modelo",
                "form_subtitle": "Cadastre um novo modelo para um provider.",
                "active_menu": "modelos",
                "submit_label": "Salvar modelo",
            }
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Modelo criado com sucesso.")
        return response


class ProviderModelUpdateView(LoginRequiredMixin, UpdateView):
    model = ProviderModel
    form_class = ProviderModelForm
    template_name = "models_catalog/form.html"
    success_url = reverse_lazy("models_catalog:list")

    def get_queryset(self):
        return ProviderModel.objects.select_related("provider")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Editar modelo",
                "form_title": "Editar modelo",
                "form_subtitle": "Atualize os dados do modelo selecionado.",
                "active_menu": "modelos",
                "submit_label": "Salvar alterações",
            }
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Modelo atualizado com sucesso.")
        return response


@login_required
@require_POST
def provider_model_toggle_status(request, pk: int):
    provider_model = get_object_or_404(ProviderModel, pk=pk)
    provider_model.is_active = not provider_model.is_active
    provider_model.save(update_fields=["is_active", "updated_at"])

    if provider_model.is_active:
        messages.success(request, "Modelo ativado com sucesso.")
    else:
        messages.success(request, "Modelo desativado com sucesso.")

    return redirect("models_catalog:list")
