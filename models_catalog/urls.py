from django.urls import path

from .views import (
    ProviderModelCreateView,
    ProviderModelListView,
    ProviderModelUpdateView,
    provider_available_models,
    provider_model_delete_legacy,
    provider_model_edit_legacy,
    provider_model_delete,
    provider_model_toggle_status_legacy,
    provider_model_toggle_status,
)

app_name = "models_catalog"

urlpatterns = [
    path("", ProviderModelListView.as_view(), name="list"),
    path("novo/", ProviderModelCreateView.as_view(), name="create"),
    path("available-models/", provider_available_models, name="available_models"),
    path("<uuid:remote_id>/editar/", ProviderModelUpdateView.as_view(), name="edit"),
    path(
        "<uuid:remote_id>/toggle-status/",
        provider_model_toggle_status,
        name="toggle_status",
    ),
    path("<uuid:remote_id>/excluir/", provider_model_delete, name="delete"),
    path("<int:pk>/editar/", provider_model_edit_legacy, name="edit_legacy"),
    path(
        "<int:pk>/toggle-status/",
        provider_model_toggle_status_legacy,
        name="toggle_status_legacy",
    ),
    path("<int:pk>/excluir/", provider_model_delete_legacy, name="delete_legacy"),
]
