from django.urls import path

from .views import FileDetailView, FileListView

app_name = "files_admin"

urlpatterns = [
    path("", FileListView.as_view(), name="list"),
    path("<str:file_id>/", FileDetailView.as_view(), name="detail"),
]
