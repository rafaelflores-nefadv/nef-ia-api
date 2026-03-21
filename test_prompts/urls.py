from django.urls import path

from .views import (
    TestPromptCreateView,
    TestPromptDeleteView,
    TestPromptDetailView,
    TestPromptExecutionCreateView,
    TestPromptExecutionDetailView,
    TestPromptExecutionOutputDownloadView,
    TestPromptListView,
    TestPromptUpdateView,
    test_prompt_duplicate,
    test_prompt_toggle_status,
)

app_name = "test_prompts"

urlpatterns = [
    path("", TestPromptListView.as_view(), name="list"),
    path("novo/", TestPromptCreateView.as_view(), name="create"),
    path("<int:pk>/", TestPromptDetailView.as_view(), name="detail"),
    path("<int:pk>/editar/", TestPromptUpdateView.as_view(), name="edit"),
    path("<int:pk>/excluir/", TestPromptDeleteView.as_view(), name="delete"),
    path("<int:pk>/executar/", TestPromptExecutionCreateView.as_view(), name="execute"),
    path("<int:pk>/execucoes/<str:execution_id>/", TestPromptExecutionDetailView.as_view(), name="execution_detail"),
    path(
        "<int:pk>/execucoes/<str:execution_id>/arquivo/",
        TestPromptExecutionOutputDownloadView.as_view(),
        name="execution_output_download",
    ),
    path("<int:pk>/toggle-status/", test_prompt_toggle_status, name="toggle_status"),
    path("<int:pk>/duplicar/", test_prompt_duplicate, name="duplicate"),
]
