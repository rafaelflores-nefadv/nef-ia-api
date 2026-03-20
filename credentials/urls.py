from django.urls import path

from .views import (
    ProviderCredentialCreateView,
    ProviderCredentialListView,
    ProviderCredentialUpdateView,
    provider_credential_edit_legacy,
    provider_credential_test_connectivity,
    provider_credential_test_connectivity_legacy,
    provider_credential_toggle_status,
    provider_credential_toggle_status_legacy,
)

app_name = "credentials"

urlpatterns = [
    path("", ProviderCredentialListView.as_view(), name="list"),
    path("nova/", ProviderCredentialCreateView.as_view(), name="create"),
    path("<uuid:remote_id>/editar/", ProviderCredentialUpdateView.as_view(), name="edit"),
    path(
        "<uuid:remote_id>/test-connectivity/",
        provider_credential_test_connectivity,
        name="test_connectivity",
    ),
    path(
        "<uuid:remote_id>/toggle-status/",
        provider_credential_toggle_status,
        name="toggle_status",
    ),
    path("<int:pk>/editar/", provider_credential_edit_legacy, name="edit_legacy"),
    path(
        "<int:pk>/test-connectivity/",
        provider_credential_test_connectivity_legacy,
        name="test_connectivity_legacy",
    ),
    path(
        "<int:pk>/toggle-status/",
        provider_credential_toggle_status_legacy,
        name="toggle_status_legacy",
    ),
]
