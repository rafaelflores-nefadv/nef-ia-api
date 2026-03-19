from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.utils import timezone
from django.views.generic import TemplateView

from core.forms import FastAPIIntegrationConfigForm, FastAPIIntegrationTokenCreateForm
from core.models import FastAPIIntegrationConfig, FastAPIIntegrationToken
from core.services.health_service import get_operational_health
from core.services.fastapi_integration_service import (
    FastAPIIntegrationService,
    FastAPIIntegrationServiceError,
)
from credentials.models import ProviderCredential
from models_catalog.models import ProviderModel
from providers.models import Provider


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        health = get_operational_health()

        providers_active = Provider.objects.filter(is_active=True).count()
        models_active = ProviderModel.objects.filter(is_active=True).count()
        credentials_active = ProviderCredential.objects.filter(is_active=True).count()

        context.update(
            {
                "page_title": "Dashboard",
                "active_menu": "dashboard",
                "providers_active": providers_active,
                "models_active": models_active,
                "credentials_active": credentials_active,
                "health_live": health["live"],
                "health_ready": health["ready"],
                "health_overall": health["overall"],
                "health_checks": health["ready"]["checks"],
                "health_errors": health["errors"],
                "last_sync_at": timezone.localtime(),
            }
        )
        return context


def _integration_status_meta(status: str) -> dict[str, str]:
    table = {
        "online": {"label": "Conectado", "css_class": "status-success"},
        "degraded": {"label": "Conexao parcial", "css_class": "status-warning"},
        "disabled": {"label": "Desativado", "css_class": "status-neutral"},
        "error": {"label": "Indisponivel", "css_class": "status-danger"},
        "unknown": {"label": "Nao testado", "css_class": "status-neutral"},
    }
    return table.get(status, table["unknown"])


class FastAPIIntegrationSettingsView(LoginRequiredMixin, TemplateView):
    template_name = "core/fastapi_integration_settings.html"

    def _get_config(self) -> FastAPIIntegrationConfig:
        return FastAPIIntegrationService.get_or_create_config()

    def _extract_token_id(self, value: str | None) -> int | None:
        raw = str(value or "").strip()
        if not raw.isdigit():
            return None
        return int(raw)

    def _build_connection_summary(
        self,
        *,
        config: FastAPIIntegrationConfig,
        selected_token: FastAPIIntegrationToken | None,
        test_result: dict | None = None,
    ) -> dict[str, str | None]:
        if test_result is not None:
            status = str(test_result.get("status") or "unknown")
            meta = _integration_status_meta(status)
            return {
                "status": status,
                "status_label": str(test_result.get("status_label") or meta["label"]),
                "status_css_class": meta["css_class"],
                "message": str(test_result.get("message") or ""),
            }

        if not config.is_active:
            meta = _integration_status_meta("disabled")
            return {
                "status": "disabled",
                "status_label": meta["label"],
                "status_css_class": meta["css_class"],
                "message": "Integracao desativada nas configuracoes.",
            }

        if selected_token is None:
            meta = _integration_status_meta("unknown")
            has_env_fallback = bool(str(getattr(settings, "FASTAPI_ADMIN_TOKEN", "") or "").strip())
            return {
                "status": "unknown",
                "status_label": meta["label"],
                "status_css_class": meta["css_class"],
                "message": "Nenhum token ativo selecionado. "
                + (
                    "Token de ambiente FASTAPI_ADMIN_TOKEN sera usado como fallback."
                    if has_env_fallback
                    else "Cadastre e selecione um token para chamadas administrativas."
                ),
            }

        if config.last_validated_at:
            meta = _integration_status_meta("online")
            validated = timezone.localtime(config.last_validated_at).strftime("%d/%m/%Y %H:%M:%S")
            return {
                "status": "online",
                "status_label": meta["label"],
                "status_css_class": meta["css_class"],
                "message": f"Ultima validacao registrada em {validated}.",
            }

        meta = _integration_status_meta("unknown")
        return {
            "status": "unknown",
            "status_label": meta["label"],
            "status_css_class": meta["css_class"],
            "message": "Configure e execute um teste para validar a conexao.",
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        config = kwargs.get("config") or self._get_config()
        form = kwargs.get("form") or FastAPIIntegrationConfigForm(instance=config)
        token_form = kwargs.get("token_form") or FastAPIIntegrationTokenCreateForm()
        tokens = kwargs.get("tokens") or FastAPIIntegrationService.list_tokens(config=config)
        selected_token = FastAPIIntegrationService.get_selected_token(
            config=config,
            active_only=True,
        )
        test_result = kwargs.get("test_result")
        created_token_value = kwargs.get("created_token_value")
        connection_summary = self._build_connection_summary(
            config=config,
            selected_token=selected_token,
            test_result=test_result,
        )

        context.update(
            {
                "page_title": "Integracao FastAPI",
                "form_title": "Integracao FastAPI",
                "form_subtitle": "Gerencie URL, status e tokens da integracao administrativa.",
                "active_menu": "configuracoes",
                "form": form,
                "token_form": token_form,
                "config": config,
                "tokens": tokens,
                "selected_token": selected_token,
                "test_result": test_result,
                "created_token_value": created_token_value,
                "connection_summary": connection_summary,
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        config = self._get_config()
        action = str(request.POST.get("action") or "save").strip().lower()
        test_result = None
        created_token_value = None

        form = FastAPIIntegrationConfigForm(instance=config)
        token_form = FastAPIIntegrationTokenCreateForm()

        if action in {"save", "test"}:
            form = FastAPIIntegrationConfigForm(request.POST, instance=config)
            if form.is_valid():
                saved_config = form.save()

                if action == "test":
                    integration_token = FastAPIIntegrationService.get_selected_token_value(
                        config=saved_config
                    )
                    if not integration_token:
                        integration_token = str(getattr(settings, "FASTAPI_ADMIN_TOKEN", "") or "").strip()
                    test_result = FastAPIIntegrationService.test_connection(
                        base_url=saved_config.base_url,
                        integration_token=integration_token,
                        is_active=saved_config.is_active,
                    )
                    if test_result.get("ok"):
                        saved_config.last_validated_at = timezone.now()
                        saved_config.save(update_fields=["last_validated_at", "updated_at"])
                        messages.success(request, "Conexao com a FastAPI validada com sucesso.")
                    else:
                        messages.warning(
                            request,
                            "Teste de conexao concluiu com pendencias. Revise URL e token selecionado.",
                        )
                else:
                    messages.success(request, "Configuracoes de integracao salvas com sucesso.")
            else:
                messages.error(request, "Nao foi possivel salvar as configuracoes informadas.")

        elif action == "create_token":
            token_form = FastAPIIntegrationTokenCreateForm(request.POST)
            if token_form.is_valid():
                token_name = token_form.cleaned_data["name"]
                try:
                    _, created_token_value = FastAPIIntegrationService.create_token_via_api(
                        config=config,
                        name=token_name,
                    )
                    token_form = FastAPIIntegrationTokenCreateForm()
                    messages.success(
                        request,
                        "Novo token criado com sucesso. Copie o valor agora, ele e exibido apenas uma vez.",
                    )
                except FastAPIIntegrationServiceError as exc:
                    messages.error(request, str(exc))
            else:
                messages.error(request, "Informe um nome valido para criar o token.")

        elif action in {"select_token", "activate_token", "deactivate_token", "revoke_token"}:
            token_id = self._extract_token_id(request.POST.get("token_id"))
            if token_id is None:
                messages.error(request, "Token informado e invalido.")
            else:
                try:
                    if action == "select_token":
                        token = FastAPIIntegrationService.select_token(config=config, token_id=token_id)
                        messages.success(request, f"Token '{token.name}' selecionado para uso.")
                    elif action == "activate_token":
                        token = FastAPIIntegrationService.set_token_status(
                            config=config,
                            token_id=token_id,
                            is_active=True,
                        )
                        messages.success(request, f"Token '{token.name}' ativado.")
                    else:
                        token = FastAPIIntegrationService.set_token_status(
                            config=config,
                            token_id=token_id,
                            is_active=False,
                        )
                        messages.success(request, f"Token '{token.name}' revogado/desativado.")
                except FastAPIIntegrationServiceError as exc:
                    messages.error(request, str(exc))

        else:
            messages.error(request, "Acao informada nao e suportada.")

        config.refresh_from_db()
        tokens = FastAPIIntegrationService.list_tokens(config=config)

        context = self.get_context_data(
            form=form,
            token_form=token_form,
            config=config,
            tokens=tokens,
            test_result=test_result,
            created_token_value=created_token_value,
        )
        return self.render_to_response(context)
