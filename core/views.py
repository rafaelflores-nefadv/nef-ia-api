from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import TemplateView

from core.services.health_service import get_operational_health
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
