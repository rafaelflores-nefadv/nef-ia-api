from django.urls import path

from .views import OperationsStatusView

app_name = "operations"

urlpatterns = [
    path("", OperationsStatusView.as_view(), name="status"),
]
