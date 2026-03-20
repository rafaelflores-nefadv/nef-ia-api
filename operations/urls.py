from django.urls import path

from .views import (
    AutomationExecutionSettingsListView,
    AutomationExecutionSettingsUpdateView,
    OperationsStatusView,
)

app_name = "operations"

urlpatterns = [
    path("", OperationsStatusView.as_view(), name="status"),
    path("perfis-execucao/", AutomationExecutionSettingsListView.as_view(), name="execution_profiles"),
    path(
        "perfis-execucao/<uuid:automation_id>/",
        AutomationExecutionSettingsUpdateView.as_view(),
        name="execution_profile_edit",
    ),
]
