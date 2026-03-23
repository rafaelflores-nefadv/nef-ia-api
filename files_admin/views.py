from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView

from core.services.files_service import FilesService


class FileListView(LoginRequiredMixin, TemplateView):
    template_name = "files_admin/list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = FilesService()

        selected_status = self.request.GET.get("status", "").strip()
        selected_type = self.request.GET.get("tipo", "").strip()
        selected_execution = self.request.GET.get("execucao", "").strip()
        search_query = self.request.GET.get("q", "").strip()

        payload = service.get_files_list(
            status=selected_status,
            file_type=selected_type,
            execution_id=selected_execution,
            query=search_query,
        )

        context.update(
            {
                "page_title": "Arquivos",
                "page_subtitle": "Visão administrativa dos arquivos da plataforma.",
                "active_menu": "arquivos",
                "files": payload["items"],
                "status_options": [
                    ("", "Todos os status"),
                    ("disponivel", "Disponível"),
                    ("processando", "Processando"),
                    ("erro", "Erro"),
                    ("arquivado", "Arquivado"),
                ],
                "type_options": payload["type_options"],
                "execution_options": payload["execution_options"],
                "selected_status": selected_status,
                "selected_type": selected_type,
                "selected_execution": selected_execution,
                "search_query": search_query,
                "filtered_count": payload["filtered_count"],
                "total_count": payload["total_count"],
                "integration_source": payload["source"],
                "integration_warnings": payload["warnings"],
                "list_counter_label": (
                    f"Exibindo {payload['filtered_count']} de {payload['total_count']} arquivos"
                ),
            }
        )
        return context


class FileDetailView(LoginRequiredMixin, TemplateView):
    template_name = "files_admin/detail.html"
    file_payload: dict | None = None

    def get(self, request, *args, **kwargs):
        file_id = self.kwargs["file_id"]
        payload = FilesService().get_file_detail(file_id)
        if not payload["found"] or payload["file_item"] is None:
            messages.error(
                request,
                str(
                    payload.get("limitation_message")
                    or "Arquivo não encontrado na consulta remota da API."
                ),
            )
            return redirect("files_admin:list")
        self.file_payload = payload
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payload = self.file_payload or {}
        file_item = payload.get("file_item") or {}
        context.update(
            {
                "page_title": f"Arquivo {file_item.get('id', '-')}",
                "active_menu": "arquivos",
                "file_item": file_item,
                "integration_source": payload.get("source", "unavailable"),
                "integration_warnings": payload.get("warnings", []),
                "integration_limitation": payload.get("limitation_message"),
            }
        )
        return context


class FileDownloadView(LoginRequiredMixin, TemplateView):
    template_name = "files_admin/detail.html"

    def get(self, request, *args, **kwargs):
        file_id = self.kwargs["file_id"]
        payload = FilesService().download_execution_file(file_id=file_id)
        if not payload.get("ok"):
            messages.error(
                request,
                str(payload.get("error") or "Falha ao realizar download remoto do arquivo."),
            )
            return redirect("files_admin:detail", file_id=file_id)

        response = HttpResponse(
            payload.get("content", b""),
            content_type=str(payload.get("content_type") or "application/octet-stream"),
        )
        filename = str(payload.get("filename") or f"{file_id}.bin")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        checksum = payload.get("checksum")
        if checksum:
            response["X-File-Checksum"] = str(checksum)
        return response
