from django.urls import include, path
from django.views.generic.base import RedirectView


urlpatterns = [
    path("accounts/", include("accounts.urls")),
    path("providers/", include("providers.urls")),
    path("modelos/", include("models_catalog.urls")),
    path("automacoes/", include("prompts.urls")),
    path("prompts/", RedirectView.as_view(url="/automacoes/", permanent=False)),
    path("prompts/<path:subpath>/", RedirectView.as_view(url="/automacoes/%(subpath)s/", permanent=False)),
    path("automacoes-teste/", include("test_automations.urls")),
    path("prompts-teste/", include("test_prompts.urls")),
    path("credenciais/", include("credentials.urls")),
    path("operacoes/", include("operations.urls")),
    path("execucoes/", include("executions.urls")),
    path("arquivos/", include("files_admin.urls")),
    path("", include("core.urls")),
]
