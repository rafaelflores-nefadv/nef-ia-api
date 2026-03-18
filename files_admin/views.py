from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = FilesService()

        file_id = self.kwargs["file_id"]
        payload = service.get_file_detail(file_id)
        if not payload["found"] or payload["file_item"] is None:
            raise Http404("Arquivo nao encontrado.")

        file_item = payload["file_item"]
        context.update(
            {
                "page_title": f"Arquivo {file_item['id']}",
                "active_menu": "arquivos",
                "file_item": file_item,
                "integration_source": payload["source"],
                "integration_warnings": payload["warnings"],
                "integration_limitation": payload["limitation_message"],
            }
        )
        return context
