from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import FormView, ListView, TemplateView

from core.services.automation_execution_settings_api_service import (
    AutomationExecutionSettingReadItem,
    AutomationExecutionSettingsAPIService,
    AutomationExecutionSettingsAPIServiceError,
)
from core.services.health_service import get_operational_health
from credentials.models import ProviderCredential
from models_catalog.models import ProviderModel
from providers.models import Provider

from .forms import AutomationExecutionProfileForm


class OperationsStatusView(LoginRequiredMixin, TemplateView):
    template_name = "operations/status.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        health = get_operational_health()

        providers_qs = Provider.objects.annotate(
            models_total=Count("provider_models", distinct=True),
            credentials_total=Count("credentials", distinct=True),
            models_active=Count(
                "provider_models",
                filter=Q(provider_models__is_active=True),
                distinct=True,
            ),
            credentials_active=Count(
                "credentials",
                filter=Q(credentials__is_active=True),
                distinct=True,
            ),
        ).order_by("name")

        providers_total = providers_qs.count()
        providers_active_total = providers_qs.filter(is_active=True).count()
        models_total = ProviderModel.objects.count()
        models_active_total = ProviderModel.objects.filter(is_active=True).count()
        credentials_total = ProviderCredential.objects.count()
        credentials_active_total = ProviderCredential.objects.filter(is_active=True).count()

        providers_without_models_qs = providers_qs.filter(models_total=0)
        providers_without_credentials_qs = providers_qs.filter(credentials_total=0)
        active_without_active_models_qs = providers_qs.filter(
            is_active=True,
            models_active=0,
        )
        active_without_active_credentials_qs = providers_qs.filter(
            is_active=True,
            credentials_active=0,
        )
        providers_without_minimum_setup_qs = providers_qs.filter(is_active=True).filter(
            Q(models_active=0) | Q(credentials_active=0)
        )

        context.update(
            {
                "page_title": "Operacoes",
                "page_subtitle": "Visao consolidada do status operacional da plataforma.",
                "active_menu": "operacoes",
                "summary_cards": [
                    {"label": "Total de providers", "value": providers_total},
                    {"label": "Providers ativos", "value": providers_active_total},
                    {"label": "Total de modelos", "value": models_total},
                    {"label": "Modelos ativos", "value": models_active_total},
                    {"label": "Total de credenciais", "value": credentials_total},
                    {"label": "Credenciais ativas", "value": credentials_active_total},
                ],
                "catalog_health": [
                    {
                        "label": "Providers sem modelos",
                        "value": providers_without_models_qs.count(),
                    },
                    {
                        "label": "Providers sem credenciais",
                        "value": providers_without_credentials_qs.count(),
                    },
                    {
                        "label": "Providers ativos sem modelos ativos",
                        "value": active_without_active_models_qs.count(),
                    },
                    {
                        "label": "Providers ativos sem credenciais ativas",
                        "value": active_without_active_credentials_qs.count(),
                    },
                ],
                "environment_status": health["environment_items"],
                "health_live": health["live"],
                "health_ready": health["ready"],
                "health_overall": health["overall"],
                "health_errors": health["errors"],
                "alerts": self._build_alerts(
                    providers_without_models_qs=providers_without_models_qs,
                    providers_without_credentials_qs=providers_without_credentials_qs,
                    active_without_active_models_qs=active_without_active_models_qs,
                    active_without_active_credentials_qs=active_without_active_credentials_qs,
                    providers_without_minimum_setup_qs=providers_without_minimum_setup_qs,
                    health=health,
                ),
                "last_updated": timezone.localtime(),
            }
        )
        return context

    def _build_alerts(
        self,
        *,
        providers_without_models_qs,
        providers_without_credentials_qs,
        active_without_active_models_qs,
        active_without_active_credentials_qs,
        providers_without_minimum_setup_qs,
        health,
    ):
        alerts = []
        if health["overall"]["status"] == "offline":
            alerts.append(
                {
                    "level": "danger",
                    "message": "FastAPI indisponivel. Exibindo dados de saude com fallback.",
                }
            )
        elif health["overall"]["status"] == "degraded":
            alerts.append(
                {
                    "level": "warning",
                    "message": "FastAPI em estado degradado. Revise checks de readiness.",
                }
            )

        for provider in active_without_active_models_qs[:3]:
            alerts.append(
                {
                    "level": "warning",
                    "message": f"Provider {provider.name} esta ativo, mas sem modelos ativos.",
                }
            )

        if active_without_active_models_qs.count() > 3:
            alerts.append(
                {
                    "level": "warning",
                    "message": (
                        f"Existem mais {active_without_active_models_qs.count() - 3} "
                        "providers ativos sem modelos ativos."
                    ),
                }
            )

        for provider in active_without_active_credentials_qs[:3]:
            alerts.append(
                {
                    "level": "warning",
                    "message": (
                        f"Provider {provider.name} esta ativo, mas sem credenciais ativas."
                    ),
                }
            )

        if active_without_active_credentials_qs.count() > 3:
            alerts.append(
                {
                    "level": "warning",
                    "message": (
                        f"Existem mais {active_without_active_credentials_qs.count() - 3} "
                        "providers ativos sem credenciais ativas."
                    ),
                }
            )

        if providers_without_models_qs.exists():
            alerts.append(
                {
                    "level": "danger",
                    "message": (
                        f"Existem {providers_without_models_qs.count()} providers sem modelos "
                        "cadastrados."
                    ),
                }
            )

        if providers_without_credentials_qs.exists():
            alerts.append(
                {
                    "level": "danger",
                    "message": (
                        f"Existem {providers_without_credentials_qs.count()} providers sem "
                        "credenciais cadastradas."
                    ),
                }
            )

        if providers_without_minimum_setup_qs.exists():
            alerts.append(
                {
                    "level": "warning",
                    "message": (
                        "Existem providers sem configuracao minima para operacao."
                    ),
                }
            )

        if not alerts:
            alerts.append(
                {
                    "level": "success",
                    "message": "Nenhum alerta operacional critico no momento.",
                }
            )

        return alerts


class AutomationExecutionSettingsListView(LoginRequiredMixin, ListView):
    template_name = "operations/execution_profiles_list.html"
    context_object_name = "items"

    def get_queryset(self):
        payload = AutomationExecutionSettingsAPIService().list_settings()
        self.integration_source = payload["source"]
        self.integration_warnings = payload["warnings"]
        return payload["items"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Perfis por automacao",
                "page_subtitle": "Configuracao administrativa persistida de perfil operacional por automacao.",
                "active_menu": "operacoes_perfis",
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
            }
        )
        return context


class AutomationExecutionSettingsUpdateView(LoginRequiredMixin, FormView):
    form_class = AutomationExecutionProfileForm
    template_name = "operations/execution_profile_form.html"
    success_url = reverse_lazy("operations:execution_profiles")
    setting_item: AutomationExecutionSettingReadItem

    def dispatch(self, request, *args, **kwargs):
        self.automation_id = kwargs["automation_id"]
        service = AutomationExecutionSettingsAPIService()
        try:
            self.setting_item = service.get_setting(automation_id=self.automation_id)
        except AutomationExecutionSettingsAPIServiceError as exc:
            messages.error(request, str(exc))
            return redirect("operations:execution_profiles")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        overrides = dict(self.setting_item.persisted_limits_overrides or {})
        initial.update(
            {
                "execution_profile": (
                    self.setting_item.persisted_execution_profile
                    or self.setting_item.resolved_execution_profile
                ),
                "is_active": (
                    True
                    if self.setting_item.persisted_is_active is None
                    else bool(self.setting_item.persisted_is_active)
                ),
                "max_execution_rows": overrides.get("max_execution_rows"),
                "max_provider_calls": overrides.get("max_provider_calls"),
                "max_text_chunks": overrides.get("max_text_chunks"),
                "max_tabular_row_characters": overrides.get("max_tabular_row_characters"),
                "max_execution_seconds": overrides.get("max_execution_seconds"),
                "max_context_characters": overrides.get("max_context_characters"),
                "max_context_file_characters": overrides.get("max_context_file_characters"),
                "max_prompt_characters": overrides.get("max_prompt_characters"),
            }
        )
        return initial

    def form_valid(self, form):
        cleaned = form.cleaned_data
        service = AutomationExecutionSettingsAPIService()
        try:
            self.setting_item = service.update_setting(
                automation_id=self.automation_id,
                execution_profile=cleaned["execution_profile"],
                is_active=bool(cleaned.get("is_active", False)),
                max_execution_rows=cleaned.get("max_execution_rows"),
                max_provider_calls=cleaned.get("max_provider_calls"),
                max_text_chunks=cleaned.get("max_text_chunks"),
                max_tabular_row_characters=cleaned.get("max_tabular_row_characters"),
                max_execution_seconds=cleaned.get("max_execution_seconds"),
                max_context_characters=cleaned.get("max_context_characters"),
                max_context_file_characters=cleaned.get("max_context_file_characters"),
                max_prompt_characters=cleaned.get("max_prompt_characters"),
            )
        except AutomationExecutionSettingsAPIServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, "Configuracao operacional atualizada com sucesso.")
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Editar perfil operacional",
                "page_subtitle": "Persistencia por automacao com fallback ativo por env/config.",
                "active_menu": "operacoes_perfis",
                "setting": self.setting_item,
            }
        )
        return context
