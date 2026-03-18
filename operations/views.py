from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.utils import timezone
from django.views.generic import TemplateView

from core.services.health_service import get_operational_health
from credentials.models import ProviderCredential
from models_catalog.models import ProviderModel
from providers.models import Provider


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
                "page_title": "Opera\u00e7\u00f5es",
                "page_subtitle": "Vis\u00e3o consolidada do status operacional da plataforma.",
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
                    "message": "FastAPI indispon\u00edvel. Exibindo dados de sa\u00fade com fallback.",
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
                    "message": f"Provider {provider.name} est\u00e1 ativo, mas sem modelos ativos.",
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
                        f"Provider {provider.name} est\u00e1 ativo, mas sem credenciais ativas."
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
                        "Existem providers sem configura\u00e7\u00e3o m\u00ednima para opera\u00e7\u00e3o."
                    ),
                }
            )

        if not alerts:
            alerts.append(
                {
                    "level": "success",
                    "message": "Nenhum alerta operacional cr\u00edtico no momento.",
                }
            )

        return alerts
