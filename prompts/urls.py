from django.urls import path

from .views import (
    AIPromptCreateView,
    AIPromptListView,
    AIPromptUpdateView,
    ai_prompt_delete,
    ai_prompt_toggle_status,
)

app_name = "prompts"

urlpatterns = [
    path("", AIPromptListView.as_view(), name="list"),
    path("novo/", AIPromptCreateView.as_view(), name="create"),
    path("<int:pk>/editar/", AIPromptUpdateView.as_view(), name="edit"),
    path("<int:pk>/toggle-status/", ai_prompt_toggle_status, name="toggle_status"),
    path("<int:pk>/excluir/", ai_prompt_delete, name="delete"),
]
