from django.urls import path

from .views import (
    ProviderModelCreateView,
    ProviderModelListView,
    ProviderModelUpdateView,
    provider_available_models,
    provider_model_delete,
    provider_model_toggle_status,
)

app_name = "models_catalog"

urlpatterns = [
    path("", ProviderModelListView.as_view(), name="list"),
    path("novo/", ProviderModelCreateView.as_view(), name="create"),
    path("available-models/", provider_available_models, name="available_models"),
    path("<int:pk>/editar/", ProviderModelUpdateView.as_view(), name="edit"),
    path("<int:pk>/toggle-status/", provider_model_toggle_status, name="toggle_status"),
    path("<int:pk>/excluir/", provider_model_delete, name="delete"),
]
