from django.urls import path

from .views import DashboardView, FastAPIIntegrationSettingsView


urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path(
        "configuracoes/integracao-fastapi/",
        FastAPIIntegrationSettingsView.as_view(),
        name="fastapi_integration_settings",
    ),
]
