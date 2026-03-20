from django.urls import path

from .views import (
    ProviderCreateView,
    ProviderListView,
    ProviderUpdateView,
    provider_edit_legacy,
    provider_test_connectivity,
    provider_test_connectivity_legacy,
    provider_toggle_status,
    provider_toggle_status_legacy,
)

app_name = "providers"

urlpatterns = [
    path("", ProviderListView.as_view(), name="list"),
    path("novo/", ProviderCreateView.as_view(), name="create"),
    path("<uuid:remote_id>/editar/", ProviderUpdateView.as_view(), name="edit"),
    path(
        "<uuid:remote_id>/test-connectivity/",
        provider_test_connectivity,
        name="test_connectivity",
    ),
    path("<uuid:remote_id>/toggle-status/", provider_toggle_status, name="toggle_status"),
    path("<int:pk>/editar/", provider_edit_legacy, name="edit_legacy"),
    path(
        "<int:pk>/test-connectivity/",
        provider_test_connectivity_legacy,
        name="test_connectivity_legacy",
    ),
    path(
        "<int:pk>/toggle-status/",
        provider_toggle_status_legacy,
        name="toggle_status_legacy",
    ),
]
