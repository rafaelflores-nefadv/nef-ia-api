from django.urls import path

from .views import (
    ProviderCredentialCreateView,
    ProviderCredentialListView,
    ProviderCredentialUpdateView,
    provider_credential_sync_api,
    provider_credential_test_connectivity,
    provider_credential_toggle_status,
)

app_name = "credentials"

urlpatterns = [
    path("", ProviderCredentialListView.as_view(), name="list"),
    path("nova/", ProviderCredentialCreateView.as_view(), name="create"),
    path("<int:pk>/editar/", ProviderCredentialUpdateView.as_view(), name="edit"),
    path("<int:pk>/sync-api/", provider_credential_sync_api, name="sync_api"),
    path("<int:pk>/test-connectivity/", provider_credential_test_connectivity, name="test_connectivity"),
    path(
        "<int:pk>/toggle-status/",
        provider_credential_toggle_status,
        name="toggle_status",
    ),
]
