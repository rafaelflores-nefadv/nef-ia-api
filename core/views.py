from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import TemplateView

from core.forms import FastAPIIntegrationConfigForm
from core.models import FastAPIIntegrationConfig
from core.services.health_service import get_operational_health
from core.services.fastapi_integration_service import FastAPIIntegrationService
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

    def _build_connection_summary(
        self,
        *,
        config: FastAPIIntegrationConfig,
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
        test_result = kwargs.get("test_result")
        connection_summary = self._build_connection_summary(
            config=config,
            test_result=test_result,
        )

        context.update(
            {
                "page_title": "Integracao FastAPI",
                "form_title": "Integracao FastAPI",
                "form_subtitle": "Gerencie URL, token e status da integracao administrativa.",
                "active_menu": "configuracoes",
                "form": form,
                "config": config,
                "test_result": test_result,
                "connection_summary": connection_summary,
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        config = self._get_config()
        form = FastAPIIntegrationConfigForm(request.POST, instance=config)
        action = str(request.POST.get("action") or "save").strip().lower()
        test_result = None

        if form.is_valid():
            saved_config = form.save()

            if action == "test":
                test_result = FastAPIIntegrationService.test_connection(
                    base_url=saved_config.base_url,
                    integration_token=saved_config.integration_token,
                    is_active=saved_config.is_active,
                )
                if test_result.get("ok"):
                    saved_config.last_validated_at = timezone.now()
                    saved_config.save(update_fields=["last_validated_at", "updated_at"])
                    messages.success(request, "Conexao com a FastAPI validada com sucesso.")
                else:
                    messages.warning(
                        request,
                        "Teste de conexao concluiu com pendencias. Revise URL e token.",
                    )
            else:
                messages.success(request, "Configuracoes de integracao salvas com sucesso.")
        else:
            messages.error(request, "Nao foi possivel salvar as configuracoes informadas.")

        context = self.get_context_data(
            form=form,
            config=config,
            test_result=test_result,
        )
        return self.render_to_response(context)
