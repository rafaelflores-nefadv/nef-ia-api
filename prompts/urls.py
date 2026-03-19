from django.urls import path

from .views import (
    AIPromptCreateView,
    AIPromptListView,
    PromptTestCreateView,
    PromptTestDetailView,
    AIPromptUpdateView,
    ai_prompt_delete,
    ai_prompt_toggle_status,
)

app_name = "prompts"

urlpatterns = [
    path("", AIPromptListView.as_view(), name="list"),
    path("novo/", AIPromptCreateView.as_view(), name="create"),
    path("teste/", PromptTestCreateView.as_view(), name="test_create"),
    path("teste/<uuid:test_id>/", PromptTestDetailView.as_view(), name="test_detail"),
    path("<int:pk>/editar/", AIPromptUpdateView.as_view(), name="edit"),
    path("<int:pk>/toggle-status/", ai_prompt_toggle_status, name="toggle_status"),
    path("<int:pk>/excluir/", ai_prompt_delete, name="delete"),
]
