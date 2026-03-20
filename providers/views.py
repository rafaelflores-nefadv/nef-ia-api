from __future__ import annotations

from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import FormView, ListView

from core.services.providers_api_service import (
    ProviderReadItem,
    ProvidersAPIService,
    ProvidersAPIServiceError,
)

from .forms import ProviderForm


def _store_provider_connectivity_result(
    request,
    *,
    remote_provider_id: UUID,
    result: dict,
) -> None:
    cache = request.session.get("provider_connectivity_results", {})
    cache[str(remote_provider_id)] = {
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


def _redirect_legacy_local_route(request, *, local_pk: int) -> object:
    messages.warning(
        request,
        (
            f"Rota legada por ID local ({local_pk}) descontinuada. "
            "Use rotas com ID remoto (UUID) para operar diretamente na FastAPI."
        ),
    )
    return redirect("providers:list")


class ProviderListView(LoginRequiredMixin, ListView):
    template_name = "providers/list.html"
    context_object_name = "providers"

    def get_queryset(self):
        payload = ProvidersAPIService().get_providers_list()
        self.providers_source = payload["source"]
        self.providers_warnings = payload["warnings"]
        return payload["items"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connectivity_results = self.request.session.get("provider_connectivity_results", {})
        providers = context.get("providers")
        if providers is not None:
            for provider in providers:
                provider.connectivity_result = None
                if provider.fastapi_provider_id is None:
                    continue
                provider.connectivity_result = connectivity_results.get(
                    str(provider.fastapi_provider_id)
                )
        context.update(
            {
                "page_title": "Providers",
                "page_subtitle": "Gestao administrativa de integracoes disponiveis.",
                "active_menu": "providers",
                "integration_source": getattr(self, "providers_source", "fallback_local"),
                "integration_warnings": getattr(self, "providers_warnings", []),
            }
        )
        return context


class ProviderCreateView(LoginRequiredMixin, FormView):
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
                "remote_provider_id": None,
                "object": None,
            }
        )
        return context

    def form_valid(self, form):
        cleaned = form.cleaned_data
        service = ProvidersAPIService()
        try:
            service.create_provider(
                name=cleaned["name"],
                slug=cleaned["slug"],
                description=cleaned.get("description", ""),
                is_active=bool(cleaned.get("is_active", False)),
            )
        except ProvidersAPIServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, "Provider criado com sucesso.")
        return redirect(self.get_success_url())


class ProviderUpdateView(LoginRequiredMixin, FormView):
    form_class = ProviderForm
    template_name = "providers/form.html"
    success_url = reverse_lazy("providers:list")
    remote_provider_id: UUID
    provider_item: ProviderReadItem

    def dispatch(self, request, *args, **kwargs):
        self.remote_provider_id = kwargs["remote_id"]
        service = ProvidersAPIService()
        try:
            self.provider_item = service.get_provider(remote_provider_id=self.remote_provider_id)
        except ProvidersAPIServiceError as exc:
            if exc.code == "provider_not_found":
                raise Http404("Provider remoto nao encontrado.") from exc
            messages.error(request, str(exc))
            return redirect("providers:list")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial.update(
            {
                "name": self.provider_item.name,
                "slug": self.provider_item.slug,
                "description": self.provider_item.description,
                "is_active": self.provider_item.is_active,
            }
        )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connectivity_results = self.request.session.get("provider_connectivity_results", {})
        latest_result = connectivity_results.get(str(self.remote_provider_id))
        context.update(
            {
                "page_title": "Editar provider",
                "form_title": "Editar provider",
                "form_subtitle": "Atualize os dados do provider selecionado.",
                "active_menu": "providers",
                "submit_label": "Salvar alteracoes",
                "is_editing": True,
                "latest_connectivity_result": latest_result,
                "remote_provider_id": self.remote_provider_id,
                "object": self.provider_item,
            }
        )
        return context

    def form_valid(self, form):
        cleaned = form.cleaned_data
        service = ProvidersAPIService()
        try:
            updated_item = service.update_provider(
                remote_provider_id=self.remote_provider_id,
                name=cleaned["name"],
                slug=cleaned["slug"],
                description=cleaned.get("description", ""),
                is_active=bool(cleaned.get("is_active", False)),
            )
        except ProvidersAPIServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        self.provider_item = updated_item
        messages.success(self.request, "Provider atualizado com sucesso.")
        return redirect(self.get_success_url())


@login_required
def provider_edit_legacy(request, pk: int):
    return _redirect_legacy_local_route(request, local_pk=pk)


@login_required
@require_POST
def provider_toggle_status(request, remote_id: UUID):
    service = ProvidersAPIService()
    try:
        provider_item = service.get_provider(remote_provider_id=remote_id)
        updated = service.set_provider_status(
            remote_provider_id=remote_id,
            target_active=not bool(provider_item.is_active),
        )
    except ProvidersAPIServiceError as exc:
        messages.error(
            request,
            f"Nao foi possivel sincronizar status do provider na FastAPI: {exc}",
        )
        return redirect("providers:list")

    if updated.is_active:
        messages.success(request, "Provider ativado com sucesso.")
    else:
        messages.success(request, "Provider desativado com sucesso.")

    return redirect("providers:list")


@login_required
@require_POST
def provider_toggle_status_legacy(request, pk: int):
    return _redirect_legacy_local_route(request, local_pk=pk)


@login_required
@require_POST
def provider_test_connectivity(request, remote_id: UUID):
    result = ProvidersAPIService().test_provider_connectivity(remote_provider_id=remote_id)
    _store_provider_connectivity_result(
        request,
        remote_provider_id=remote_id,
        result=result,
    )
    _publish_provider_connectivity_message(request, result=result)

    next_url = str(request.POST.get("next") or "").strip()
    if next_url:
        return redirect(next_url)
    return redirect("providers:list")


@login_required
@require_POST
def provider_test_connectivity_legacy(request, pk: int):
    return _redirect_legacy_local_route(request, local_pk=pk)
