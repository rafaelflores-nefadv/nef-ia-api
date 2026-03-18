from django.urls import path

from .views import ExecutionDetailView, ExecutionListView

app_name = "executions"

urlpatterns = [
    path("", ExecutionListView.as_view(), name="list"),
    path("<str:execution_id>/", ExecutionDetailView.as_view(), name="detail"),
]
