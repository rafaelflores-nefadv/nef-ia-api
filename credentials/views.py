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

from core.services.provider_credentials_api_service import (
    ProviderCredentialReadItem,
    ProviderCredentialsAPIService,
    ProviderCredentialsAPIServiceError,
)
from core.services.providers_api_service import ProvidersAPIService

from .forms import ProviderCredentialForm


def _store_connectivity_result(request, *, provider_remote_id: UUID, result: dict) -> None:
    cache = request.session.get("provider_connectivity_results", {})
    cache[str(provider_remote_id)] = {
        "ok": bool(result.get("ok")),
        "status": str(result.get("status") or ""),
        "status_label": str(result.get("status_label") or ""),
        "message": str(result.get("message") or ""),
        "error_code": str(result.get("error_code") or ""),
    }
    request.session["provider_connectivity_results"] = cache


def _store_sync_result(
    request,
    *,
    remote_credential_id: UUID,
    result: dict,
) -> None:
    cache = request.session.get("credential_sync_results", {})
    cache[str(remote_credential_id)] = {
        "ok": bool(result.get("ok")),
        "status": str(result.get("status") or ""),
        "status_label": str(result.get("status_label") or ""),
        "message": str(result.get("message") or ""),
        "error_code": str(result.get("error_code") or ""),
        "operation": str(result.get("operation") or ""),
    }
    request.session["credential_sync_results"] = cache


def _build_success_result(*, message: str, operation: str) -> dict:
    return {
        "ok": True,
        "status": "api_synced",
        "status_label": "Sincronizada",
        "message": str(message),
        "error_code": "",
        "operation": str(operation),
    }


def _error_result_from_exception(exc: ProviderCredentialsAPIServiceError) -> dict:
    return {
        "ok": False,
        "status": "sync_error",
        "status_label": "Erro de sincronizacao",
        "message": str(exc),
        "error_code": str(exc.code or ""),
        "operation": "error",
    }


def _format_sync_exception(exc: ProviderCredentialsAPIServiceError) -> str:
    if exc.code:
        return f"{exc} (codigo: {exc.code})"
    return str(exc)


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


def _redirect_legacy_local_route(request, *, local_pk: int) -> object:
    messages.warning(
        request,
        (
            f"Rota legada por ID local ({local_pk}) descontinuada. "
            "Use rotas com ID remoto (UUID) para operar diretamente na FastAPI."
        ),
    )
    return redirect("credentials:list")


class ProviderCredentialListView(LoginRequiredMixin, ListView):
    template_name = "credentials/list.html"
    context_object_name = "credentials"

    def get_queryset(self):
        payload = ProviderCredentialsAPIService().get_credentials_list()
        self.credentials_source = payload["source"]
        self.credentials_warnings = payload["warnings"]
        return payload["items"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connectivity_results = self.request.session.get("provider_connectivity_results", {})
        sync_results = self.request.session.get("credential_sync_results", {})
        credentials = context.get("credentials")
        if credentials is not None:
            for credential in credentials:
                provider_remote_id = credential.provider.remote_id
                credential_remote_id = credential.fastapi_credential_id
                credential.connectivity_result = (
                    connectivity_results.get(str(provider_remote_id))
                    if provider_remote_id is not None
                    else None
                )
                credential.sync_result = (
                    sync_results.get(str(credential_remote_id))
                    if credential_remote_id is not None
                    else None
                )
        context.update(
            {
                "page_title": "Credenciais",
                "page_subtitle": "Gestao administrativa de credenciais por provider.",
                "active_menu": "credenciais",
                "integration_source": getattr(self, "credentials_source", "fallback_local"),
                "integration_warnings": getattr(self, "credentials_warnings", []),
            }
        )
        return context


class ProviderCredentialCreateView(LoginRequiredMixin, FormView):
    form_class = ProviderCredentialForm
    template_name = "credentials/form.html"
    success_url = reverse_lazy("credentials:list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        provider_choices_payload = ProviderCredentialsAPIService().get_provider_choices()
        self.provider_choices_source = provider_choices_payload["source"]
        self.provider_choices_warnings = provider_choices_payload["warnings"]
        kwargs["provider_choices"] = provider_choices_payload["choices"]
        kwargs["is_editing"] = False
        kwargs["lock_provider"] = False
        return kwargs

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
                "object": None,
                "remote_credential_id": None,
                "integration_source": getattr(
                    self,
                    "provider_choices_source",
                    "unavailable",
                ),
                "integration_warnings": getattr(
                    self,
                    "provider_choices_warnings",
                    [],
                ),
            }
        )
        return context

    def form_valid(self, form):
        provider_value = str(form.cleaned_data.get("provider") or "").strip()
        try:
            remote_provider_id = UUID(provider_value)
        except ValueError:
            form.add_error("provider", "Provider remoto inválido.")
            return self.form_invalid(form)

        try:
            created_item = ProviderCredentialsAPIService().create_credential(
                remote_provider_id=remote_provider_id,
                credential_name=form.cleaned_data["name"],
                api_key=form.cleaned_data["api_key"],
                config_json=form.cleaned_data.get("config_json"),
                is_active=bool(form.cleaned_data.get("is_active", False)),
            )
        except ProviderCredentialsAPIServiceError as exc:
            form.add_error(None, _format_sync_exception(exc))
            return self.form_invalid(form)

        if created_item.fastapi_credential_id is not None:
            _store_sync_result(
                self.request,
                remote_credential_id=created_item.fastapi_credential_id,
                result=_build_success_result(
                    message="Credencial criada diretamente na FastAPI.",
                    operation="created",
                ),
            )
        messages.success(self.request, "Credencial criada com sucesso.")
        return redirect(self.get_success_url())


class ProviderCredentialUpdateView(LoginRequiredMixin, FormView):
    form_class = ProviderCredentialForm
    template_name = "credentials/form.html"
    success_url = reverse_lazy("credentials:list")
    remote_credential_id: UUID
    credential_item: ProviderCredentialReadItem

    def dispatch(self, request, *args, **kwargs):
        self.remote_credential_id = kwargs["remote_id"]
        try:
            self.credential_item = ProviderCredentialsAPIService().get_credential(
                remote_credential_id=self.remote_credential_id
            )
        except ProviderCredentialsAPIServiceError as exc:
            if exc.code == "provider_credential_not_found":
                raise Http404("Credencial remota não encontrada.") from exc
            messages.error(request, str(exc))
            return redirect("credentials:list")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial.update(
            {
                "provider": str(self.credential_item.provider.remote_id or ""),
                "name": self.credential_item.name,
                "is_active": self.credential_item.is_active,
            }
        )
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        provider_choices_payload = ProviderCredentialsAPIService().get_provider_choices()
        self.provider_choices_source = provider_choices_payload["source"]
        self.provider_choices_warnings = provider_choices_payload["warnings"]
        kwargs["provider_choices"] = provider_choices_payload["choices"]
        kwargs["is_editing"] = True
        kwargs["lock_provider"] = True
        kwargs["initial_config_json"] = self.credential_item.config_json
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connectivity_results = self.request.session.get("provider_connectivity_results", {})
        sync_results = self.request.session.get("credential_sync_results", {})
        context.update(
            {
                "page_title": "Editar credencial",
                "form_title": "Editar credencial",
                "form_subtitle": "Atualize os dados da credencial selecionada.",
                "active_menu": "credenciais",
                "submit_label": "Salvar alterações",
                "is_editing": True,
                "latest_connectivity_result": connectivity_results.get(
                    str(self.credential_item.provider.remote_id)
                ),
                "latest_sync_result": sync_results.get(str(self.remote_credential_id)),
                "object": self.credential_item,
                "remote_credential_id": self.remote_credential_id,
                "integration_source": getattr(
                    self,
                    "provider_choices_source",
                    "unavailable",
                ),
                "integration_warnings": getattr(
                    self,
                    "provider_choices_warnings",
                    [],
                ),
            }
        )
        return context

    def form_valid(self, form):
        try:
            updated_item = ProviderCredentialsAPIService().update_credential(
                remote_credential_id=self.remote_credential_id,
                credential_name=form.cleaned_data["name"],
                api_key=form.cleaned_data.get("api_key"),
                config_json=form.cleaned_data.get("config_json"),
                is_active=bool(form.cleaned_data.get("is_active", False)),
            )
        except ProviderCredentialsAPIServiceError as exc:
            form.add_error(None, _format_sync_exception(exc))
            return self.form_invalid(form)

        self.credential_item = updated_item

        _store_sync_result(
            self.request,
            remote_credential_id=self.remote_credential_id,
            result=_build_success_result(
                message="Credencial atualizada diretamente na FastAPI.",
                operation="updated",
            ),
        )
        messages.success(self.request, "Credencial atualizada com sucesso.")
        return redirect(self.get_success_url())


@login_required
@require_POST
def provider_credential_toggle_status(request, remote_id: UUID):
    service = ProviderCredentialsAPIService()
    try:
        current = service.get_credential(remote_credential_id=remote_id)
        updated = service.set_credential_status(
            remote_credential_id=remote_id,
            target_active=not bool(current.is_active),
        )
    except ProviderCredentialsAPIServiceError as exc:
        _store_sync_result(
            request,
            remote_credential_id=remote_id,
            result=_error_result_from_exception(exc),
        )
        messages.error(request, _format_sync_exception(exc))
        return redirect("credentials:list")

    _store_sync_result(
        request,
        remote_credential_id=remote_id,
        result=_build_success_result(
            message=(
                "Credencial ativada diretamente na FastAPI."
                if updated.is_active
                else "Credencial desativada diretamente na FastAPI."
            ),
            operation="status_updated",
        ),
    )

    if updated.is_active:
        messages.success(request, "Credencial ativada com sucesso.")
    else:
        messages.success(request, "Credencial desativada com sucesso.")
    return redirect("credentials:list")


@login_required
@require_POST
def provider_credential_toggle_status_legacy(request, pk: int):
    return _redirect_legacy_local_route(request, local_pk=pk)


@login_required
@require_POST
def provider_credential_test_connectivity(request, remote_id: UUID):
    service = ProviderCredentialsAPIService()
    try:
        credential = service.get_credential(remote_credential_id=remote_id)
    except ProviderCredentialsAPIServiceError as exc:
        messages.error(request, _format_sync_exception(exc))
        next_url = str(request.POST.get("next") or "").strip()
        if next_url:
            return redirect(next_url)
        return redirect("credentials:list")

    provider_remote_id = credential.provider.remote_id
    if provider_remote_id is None:
        messages.error(
            request,
            "Provider remoto não identificado para esta credencial.",
        )
        next_url = str(request.POST.get("next") or "").strip()
        if next_url:
            return redirect(next_url)
        return redirect("credentials:list")

    result = ProvidersAPIService().test_provider_connectivity(
        remote_provider_id=provider_remote_id
    )

    _store_connectivity_result(
        request,
        provider_remote_id=provider_remote_id,
        result=result,
    )
    _publish_connectivity_message(request, result=result)

    next_url = str(request.POST.get("next") or "").strip()
    if next_url:
        return redirect(next_url)
    return redirect("credentials:list")


@login_required
def provider_credential_edit_legacy(request, pk: int):
    return _redirect_legacy_local_route(request, local_pk=pk)


@login_required
@require_POST
def provider_credential_test_connectivity_legacy(request, pk: int):
    return _redirect_legacy_local_route(request, local_pk=pk)
