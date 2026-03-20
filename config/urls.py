from django.urls import include, path


urlpatterns = [
    path("accounts/", include("accounts.urls")),
    path("providers/", include("providers.urls")),
    path("modelos/", include("models_catalog.urls")),
    path("prompts/", include("prompts.urls")),
    path("prompts-teste/", include("test_prompts.urls")),
    path("credenciais/", include("credentials.urls")),
    path("operacoes/", include("operations.urls")),
    path("execucoes/", include("executions.urls")),
    path("arquivos/", include("files_admin.urls")),
    path("", include("core.urls")),
]
