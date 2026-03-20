from django.urls import path

from .views import (
    AutomationExecutionCreateView,
    AutomationExecutionDetailView,
    AutomationExecutionFileDownloadView,
    AutomationPromptListView,
)

app_name = "prompts"

urlpatterns = [
    path("", AutomationPromptListView.as_view(), name="list"),
    path("executar/", AutomationExecutionCreateView.as_view(), name="execute"),
    path("execucoes/<str:execution_id>/", AutomationExecutionDetailView.as_view(), name="execution_detail"),
    path("arquivos/<str:file_id>/download/", AutomationExecutionFileDownloadView.as_view(), name="execution_file_download"),
]
