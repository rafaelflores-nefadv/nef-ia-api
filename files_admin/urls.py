from django.urls import path

from .views import FileDetailView, FileDownloadView, FileListView

app_name = "files_admin"

urlpatterns = [
    path("", FileListView.as_view(), name="list"),
    path("<str:file_id>/", FileDetailView.as_view(), name="detail"),
    path("<str:file_id>/download/", FileDownloadView.as_view(), name="download"),
]
