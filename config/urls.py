from django.urls import include, path


urlpatterns = [
    path("accounts/", include("accounts.urls")),
    path("providers/", include("providers.urls")),
    path("", include("core.urls")),
]
