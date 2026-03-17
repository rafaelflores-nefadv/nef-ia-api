from django.urls import include, path


urlpatterns = [
    path("accounts/", include("accounts.urls")),
    path("providers/", include("providers.urls")),
    path("modelos/", include("models_catalog.urls")),
    path("", include("core.urls")),
]
