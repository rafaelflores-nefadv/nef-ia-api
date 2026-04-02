from django.urls import path

from .views import (
    AutomationExecutionCreateView,
    AutomationExecutionDetailView,
    AutomationExecutionFileDownloadView,
    AutomationExecutionStatusView,
    OfficialExpectedResultAssistantAdvancedApplyApiView,
    OfficialExpectedResultAssistantAdvancedPreviewApiView,
    OfficialAutomationDeleteView,
    OfficialAutomationDetailView,
    OfficialAutomationListView,
    OfficialExpectedResultAssistantSimpleApplyApiView,
    OfficialExpectedResultAssistantSimplePreviewApiView,
    OfficialExpectedResultAssistantView,
    OfficialAutomationPromptDetailView,
    OfficialAutomationPromptUpdateView,
    OfficialAutomationProviderCredentialsView,
    OfficialAutomationProviderModelsView,
    OfficialAutomationUpdateView,
    official_automation_toggle_status,
)

app_name = "prompts"

urlpatterns = [
    path("", OfficialAutomationListView.as_view(), name="list"),
    path(
        "assistente-resultado-esperado/",
        OfficialExpectedResultAssistantView.as_view(),
        name="expected_result_assistant",
    ),
    path(
        "assistente-resultado-esperado/api/simple-preview/",
        OfficialExpectedResultAssistantSimplePreviewApiView.as_view(),
        name="expected_result_assistant_simple_preview_api",
    ),
    path(
        "assistente-resultado-esperado/api/simple-apply/",
        OfficialExpectedResultAssistantSimpleApplyApiView.as_view(),
        name="expected_result_assistant_simple_apply_api",
    ),
    path(
        "assistente-resultado-esperado/api/advanced-preview/",
        OfficialExpectedResultAssistantAdvancedPreviewApiView.as_view(),
        name="expected_result_assistant_advanced_preview_api",
    ),
    path(
        "assistente-resultado-esperado/api/advanced-apply/",
        OfficialExpectedResultAssistantAdvancedApplyApiView.as_view(),
        name="expected_result_assistant_advanced_apply_api",
    ),
    path("modelos/", OfficialAutomationProviderModelsView.as_view(), name="provider_models"),
    path("credenciais/", OfficialAutomationProviderCredentialsView.as_view(), name="provider_credentials"),
    path("<uuid:automation_id>/", OfficialAutomationDetailView.as_view(), name="detail"),
    path("<uuid:automation_id>/prompt/", OfficialAutomationPromptDetailView.as_view(), name="prompt_detail"),
    path("<uuid:automation_id>/prompt/editar/", OfficialAutomationPromptUpdateView.as_view(), name="prompt_edit"),
    path("<uuid:automation_id>/editar/", OfficialAutomationUpdateView.as_view(), name="edit"),
    path("<uuid:automation_id>/toggle-status/", official_automation_toggle_status, name="toggle_status"),
    path("<uuid:automation_id>/excluir/", OfficialAutomationDeleteView.as_view(), name="delete"),
    # Rotas legadas de execucao real mantidas internamente por compatibilidade.
    path("executar/", AutomationExecutionCreateView.as_view(), name="execute"),
    path("execucoes/<str:execution_id>/", AutomationExecutionDetailView.as_view(), name="execution_detail"),
    path("execucoes/<str:execution_id>/status/", AutomationExecutionStatusView.as_view(), name="execution_status"),
    path("arquivos/<str:file_id>/download/", AutomationExecutionFileDownloadView.as_view(), name="execution_file_download"),
]
