from django.urls import path

from .views import (
    ProviderCreateView,
    ProviderListView,
    ProviderUpdateView,
    provider_test_connectivity,
    provider_toggle_status,
)

app_name = "providers"

urlpatterns = [
    path("", ProviderListView.as_view(), name="list"),
    path("novo/", ProviderCreateView.as_view(), name="create"),
    path("<int:pk>/editar/", ProviderUpdateView.as_view(), name="edit"),
    path("<int:pk>/test-connectivity/", provider_test_connectivity, name="test_connectivity"),
    path("<int:pk>/toggle-status/", provider_toggle_status, name="toggle_status"),
]
