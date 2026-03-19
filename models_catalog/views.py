from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, ListView, UpdateView

from core.services.provider_models_service import (
    ProviderModelsService,
    ProviderModelsServiceError,
)
from providers.models import Provider

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

    def _resolve_selected_provider(self) -> Provider | None:
        provider_value = (
            self.request.POST.get("provider")
            if self.request.method == "POST"
            else self.request.GET.get("provider")
        )
        if not provider_value:
            return None
        try:
            return Provider.objects.get(pk=int(provider_value))
        except (TypeError, ValueError, Provider.DoesNotExist):
            return None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        selected_provider = self._resolve_selected_provider()
        selected_model_key = (
            self.request.POST.get("known_model")
            if self.request.method == "POST"
            else self.request.GET.get("model")
        )
        if selected_provider is not None:
            kwargs["catalog_provider_id"] = selected_provider.pk
            kwargs["catalog_model_key"] = selected_model_key
            kwargs["available_models_payload"] = ProviderModelsService().get_available_models(
                provider=selected_provider
            )
        elif self.request.method == "GET":
            kwargs["catalog_provider_id"] = self.request.GET.get("provider")
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Novo modelo",
                "form_title": "Novo modelo",
                "form_subtitle": (
                    "Selecione um modelo disponivel do provider via FastAPI para manter o catalogo consistente."
                ),
                "active_menu": "modelos",
                "submit_label": "Salvar modelo",
                "is_create_mode": True,
                "available_models_endpoint": reverse_lazy("models_catalog:available_models"),
            }
        )
        return context

    def form_valid(self, form):
        provider = form.cleaned_data["provider"]
        known_model = form.selected_known_model or {}
        model_name = str(known_model.get("name") or "").strip()
        model_slug = str(known_model.get("slug") or "").strip().lower()
        if not model_name or not model_slug:
            form.add_error("known_model", "Modelo selecionado invalido para cadastro remoto.")
            return self.form_invalid(form)

        try:
            remote_model = ProviderModelsService().create_remote_model(
                provider=provider,
                model_name=model_name,
                model_slug=model_slug,
                context_window=form.cleaned_data.get("context_window"),
                input_cost_per_1k=form.cleaned_data.get("input_cost_per_1k"),
                output_cost_per_1k=form.cleaned_data.get("output_cost_per_1k"),
                is_active=bool(form.cleaned_data.get("is_active", True)),
            )
        except ProviderModelsServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        instance = form.save(commit=False)
        instance.name = str(remote_model.get("model_name") or model_name).strip()
        instance.slug = str(remote_model.get("model_slug") or model_slug).strip().lower()
        remote_model_id_raw = str(remote_model.get("id") or "").strip()
        if remote_model_id_raw:
            try:
                instance.fastapi_model_id = UUID(remote_model_id_raw)
            except ValueError:
                instance.fastapi_model_id = None
        instance.save()
        self.object = instance
        messages.success(self.request, "Modelo criado com sucesso.")
        return redirect(self.get_success_url())


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
        try:
            ProviderModelsService().update_remote_model(
                fastapi_model_id=self.object.fastapi_model_id,
                context_window=form.cleaned_data.get("context_window"),
                input_cost_per_1k=form.cleaned_data.get("input_cost_per_1k"),
                output_cost_per_1k=form.cleaned_data.get("output_cost_per_1k"),
                is_active=bool(form.cleaned_data.get("is_active", True)),
            )
        except ProviderModelsServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        response = super().form_valid(form)
        messages.success(self.request, "Modelo atualizado com sucesso.")
        return response


@login_required
@require_POST
def provider_model_toggle_status(request, pk: int):
    provider_model = get_object_or_404(ProviderModel, pk=pk)
    new_status = not bool(provider_model.is_active)
    try:
        ProviderModelsService().update_remote_model(
            fastapi_model_id=provider_model.fastapi_model_id,
            context_window=provider_model.context_window,
            input_cost_per_1k=provider_model.input_cost_per_1k,
            output_cost_per_1k=provider_model.output_cost_per_1k,
            is_active=new_status,
        )
    except ProviderModelsServiceError as exc:
        messages.error(request, f"Nao foi possivel sincronizar status do modelo na FastAPI: {exc}")
        return redirect("models_catalog:list")

    provider_model.is_active = new_status
    provider_model.save(update_fields=["is_active", "updated_at"])

    if provider_model.is_active:
        messages.success(request, "Modelo ativado com sucesso.")
    else:
        messages.success(request, "Modelo desativado com sucesso.")

    return redirect("models_catalog:list")


@login_required
@require_POST
def provider_model_delete(request, pk: int):
    provider_model = get_object_or_404(ProviderModel, pk=pk)
    model_name = str(provider_model.name or "").strip() or "modelo"

    try:
        provider_model.delete()
    except ProtectedError:
        messages.error(
            request,
            "Nao foi possivel excluir este modelo porque existem vinculos que impedem a exclusao.",
        )
        return redirect("models_catalog:list")
    except IntegrityError:
        messages.error(
            request,
            "Nao foi possivel excluir este modelo no momento. Verifique se ele possui vinculacoes ativas.",
        )
        return redirect("models_catalog:list")
    except Exception:
        messages.error(
            request,
            "Nao foi possivel excluir este modelo no momento. Tente novamente.",
        )
        return redirect("models_catalog:list")

    messages.success(request, f'Modelo "{model_name}" excluido com sucesso.')
    return redirect("models_catalog:list")


@login_required
@require_GET
def provider_available_models(request):
    provider_value = str(request.GET.get("provider") or "").strip()
    if not provider_value.isdigit():
        return JsonResponse(
            {
                "items": [],
                "source": "unavailable",
                "warnings": ["Provider informado e invalido."],
                "provider_remote_id": None,
            },
            status=400,
        )

    provider = Provider.objects.filter(pk=int(provider_value)).first()
    if provider is None:
        return JsonResponse(
            {
                "items": [],
                "source": "unavailable",
                "warnings": ["Provider nao encontrado."],
                "provider_remote_id": None,
            },
            status=404,
        )

    payload = ProviderModelsService().get_available_models(provider=provider)
    return JsonResponse(payload, status=200)
