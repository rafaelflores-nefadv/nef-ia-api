from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from .forms import ProviderModelCreateForm, ProviderModelUpdateForm
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
                "page_subtitle": "Catalogo administrativo de modelos de IA.",
                "active_menu": "modelos",
            }
        )
        return context


class ProviderModelCreateView(LoginRequiredMixin, CreateView):
    model = ProviderModel
    form_class = ProviderModelCreateForm
    template_name = "models_catalog/form.html"
    success_url = reverse_lazy("models_catalog:list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method == "GET":
            kwargs["catalog_provider_id"] = self.request.GET.get("provider")
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Novo modelo",
                "form_title": "Novo modelo",
                "form_subtitle": (
                    "Selecione um modelo conhecido do provider para manter o catalogo consistente."
                ),
                "active_menu": "modelos",
                "submit_label": "Salvar modelo",
                "is_create_mode": True,
            }
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Modelo criado com sucesso.")
        return response


class ProviderModelUpdateView(LoginRequiredMixin, UpdateView):
    model = ProviderModel
    form_class = ProviderModelUpdateForm
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
                "form_subtitle": (
                    "Provider e identificacao do modelo ficam bloqueados para preservar consistencia."
                ),
                "active_menu": "modelos",
                "submit_label": "Salvar alteracoes",
                "is_create_mode": False,
                "locked_provider_name": self.object.provider.name,
                "locked_model_name": self.object.name,
                "locked_model_slug": self.object.slug,
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
