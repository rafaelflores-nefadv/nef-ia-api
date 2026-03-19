from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from core.services.provider_connectivity_service import ProviderConnectivityClientService
from core.services.provider_credentials_service import (
    ProviderCredentialSyncError,
    ProviderCredentialSyncResult,
    ProviderCredentialsService,
)

from .forms import ProviderCredentialForm
from .models import ProviderCredential


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


def _store_sync_result(request, *, credential_id: int, result: dict) -> None:
    cache = request.session.get("credential_sync_results", {})
    cache[str(credential_id)] = {
        "ok": bool(result.get("ok")),
        "status": str(result.get("status") or ""),
        "status_label": str(result.get("status_label") or ""),
        "message": str(result.get("message") or ""),
        "error_code": str(result.get("error_code") or ""),
        "operation": str(result.get("operation") or ""),
    }
    request.session["credential_sync_results"] = cache


def _result_from_sync(sync_result: ProviderCredentialSyncResult) -> dict:
    return {
        "ok": bool(sync_result.ok),
        "status": str(sync_result.status),
        "status_label": str(sync_result.status_label),
        "message": str(sync_result.message),
        "error_code": str(sync_result.error_code or ""),
        "operation": str(sync_result.operation or ""),
    }


def _error_result_from_exception(exc: ProviderCredentialSyncError) -> dict:
    return {
        "ok": False,
        "status": "sync_error",
        "status_label": "Erro de sincronizacao",
        "message": str(exc),
        "error_code": str(exc.code or ""),
        "operation": "error",
    }


def _format_sync_exception(exc: ProviderCredentialSyncError) -> str:
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
        sync_results = self.request.session.get("credential_sync_results", {})
        credentials = context.get("credentials")
        if credentials is not None:
            for credential in credentials:
                credential.connectivity_result = connectivity_results.get(str(credential.provider_id))
                credential.sync_result = sync_results.get(str(credential.id))
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
        candidate = form.save(commit=False)
        candidate.fastapi_credential_id = None

        try:
            sync_result = ProviderCredentialsService().sync_credential(credential=candidate)
        except ProviderCredentialSyncError as exc:
            form.add_error(None, _format_sync_exception(exc))
            return self.form_invalid(form)

        candidate.fastapi_credential_id = sync_result.remote_credential_id
        candidate.save()
        self.object = candidate

        _store_sync_result(
            self.request,
            credential_id=self.object.id,
            result=_result_from_sync(sync_result),
        )
        messages.success(self.request, "Credencial criada com sucesso. " + sync_result.message)
        return redirect(self.get_success_url())


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
        sync_results = self.request.session.get("credential_sync_results", {})
        context.update(
            {
                "page_title": "Editar credencial",
                "form_title": "Editar credencial",
                "form_subtitle": "Atualize os dados da credencial selecionada.",
                "active_menu": "credenciais",
                "submit_label": "Salvar alteracoes",
                "is_editing": True,
                "latest_connectivity_result": connectivity_results.get(str(self.object.provider_id)),
                "latest_sync_result": sync_results.get(str(self.object.id)),
            }
        )
        return context

    def form_valid(self, form):
        persisted = ProviderCredential.objects.select_related("provider").get(pk=form.instance.pk)
        candidate = form.save(commit=False)
        candidate.fastapi_credential_id = persisted.fastapi_credential_id

        try:
            sync_result = ProviderCredentialsService().sync_credential(
                credential=candidate,
                previous_provider_id=persisted.provider_id,
            )
        except ProviderCredentialSyncError as exc:
            form.add_error(None, _format_sync_exception(exc))
            return self.form_invalid(form)

        candidate.fastapi_credential_id = sync_result.remote_credential_id
        candidate.save()
        self.object = candidate

        _store_sync_result(
            self.request,
            credential_id=self.object.id,
            result=_result_from_sync(sync_result),
        )
        messages.success(self.request, "Credencial atualizada com sucesso. " + sync_result.message)
        return redirect(self.get_success_url())


@login_required
@require_POST
def provider_credential_toggle_status(request, pk: int):
    credential = get_object_or_404(
        ProviderCredential.objects.select_related("provider"),
        pk=pk,
    )
    new_status = not bool(credential.is_active)
    credential.is_active = new_status

    try:
        sync_result = ProviderCredentialsService().sync_credential_status(
            credential=credential,
            target_active=new_status,
        )
    except ProviderCredentialSyncError as exc:
        _store_sync_result(
            request,
            credential_id=credential.id,
            result=_error_result_from_exception(exc),
        )
        messages.error(request, _format_sync_exception(exc))
        return redirect("credentials:list")

    credential.fastapi_credential_id = sync_result.remote_credential_id or credential.fastapi_credential_id
    credential.save(update_fields=["is_active", "fastapi_credential_id", "updated_at"])
    _store_sync_result(
        request,
        credential_id=credential.id,
        result=_result_from_sync(sync_result),
    )

    if credential.is_active:
        messages.success(request, "Credencial ativada com sucesso.")
    else:
        messages.success(request, "Credencial desativada com sucesso.")
    return redirect("credentials:list")


@login_required
@require_POST
def provider_credential_sync_api(request, pk: int):
    credential = get_object_or_404(
        ProviderCredential.objects.select_related("provider"),
        pk=pk,
    )
    service = ProviderCredentialsService()
    try:
        sync_result = service.sync_credential(
            credential=credential,
            previous_provider_id=credential.provider_id,
        )
    except ProviderCredentialSyncError as exc:
        _store_sync_result(
            request,
            credential_id=credential.id,
            result=_error_result_from_exception(exc),
        )
        messages.error(request, _format_sync_exception(exc))
        next_url = str(request.POST.get("next") or "").strip()
        if next_url:
            return redirect(next_url)
        return redirect("credentials:list")

    remote_id = sync_result.remote_credential_id
    if remote_id is not None and credential.fastapi_credential_id != remote_id:
        credential.fastapi_credential_id = remote_id
        credential.save(update_fields=["fastapi_credential_id", "updated_at"])

    _store_sync_result(
        request,
        credential_id=credential.id,
        result=_result_from_sync(sync_result),
    )
    messages.success(request, sync_result.message)

    next_url = str(request.POST.get("next") or "").strip()
    if next_url:
        return redirect(next_url)
    return redirect("credentials:list")


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
