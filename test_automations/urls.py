from django.urls import path

from .views import (
    TestAutomationCopyToOfficialView,
    TestAutomationCreateView,
    TestAutomationDeleteView,
    TestAutomationDetailView,
    TestAutomationProviderCredentialsView,
    TestAutomationListView,
    TestAutomationProviderModelsView,
    TestAutomationUpdateView,
)

app_name = "test_automations"

urlpatterns = [
    path("", TestAutomationListView.as_view(), name="list"),
    path("nova/", TestAutomationCreateView.as_view(), name="create"),
    path("modelos/", TestAutomationProviderModelsView.as_view(), name="provider_models"),
    path("credenciais/", TestAutomationProviderCredentialsView.as_view(), name="provider_credentials"),
    path("<uuid:automation_id>/", TestAutomationDetailView.as_view(), name="detail"),
    path("<uuid:automation_id>/copiar-para-oficial/", TestAutomationCopyToOfficialView.as_view(), name="copy_to_official"),
    path("<uuid:automation_id>/editar/", TestAutomationUpdateView.as_view(), name="edit"),
    path("<uuid:automation_id>/excluir/", TestAutomationDeleteView.as_view(), name="delete"),
]
