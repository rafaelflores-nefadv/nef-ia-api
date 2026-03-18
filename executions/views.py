from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.views.generic import TemplateView

from core.services.executions_service import ExecutionsService


PERIOD_OPTIONS = [
    ("", "Todos os periodos"),
    ("24h", "Ultimas 24 horas"),
    ("7d", "Ultimos 7 dias"),
    ("30d", "Ultimos 30 dias"),
]


class ExecutionListView(LoginRequiredMixin, TemplateView):
    template_name = "executions/list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = ExecutionsService()

        selected_status = self.request.GET.get("status", "").strip()
        selected_provider = self.request.GET.get("provider", "").strip()
        selected_period = self.request.GET.get("periodo", "").strip()
        search_query = self.request.GET.get("q", "").strip()

        payload = service.get_execution_list(
            status=selected_status,
            provider=selected_provider,
            period=selected_period,
            query=search_query,
        )

        context.update(
            {
                "page_title": "Execucoes",
                "page_subtitle": "Visao administrativa das execucoes da plataforma.",
                "active_menu": "execucoes",
                "executions": payload["items"],
                "status_options": [
                    ("", "Todos os status"),
                    ("pendente", "Pendente"),
                    ("em_andamento", "Em andamento"),
                    ("concluida", "Concluida"),
                    ("falhou", "Falhou"),
                ],
                "provider_options": payload["provider_options"],
                "period_options": PERIOD_OPTIONS,
                "selected_status": selected_status,
                "selected_provider": selected_provider,
                "selected_period": selected_period,
                "search_query": search_query,
                "filtered_count": payload["filtered_count"],
                "total_count": payload["total_count"],
                "integration_source": payload["source"],
                "integration_warnings": payload["warnings"],
                "list_counter_label": (
                    f"Exibindo {payload['filtered_count']} de {payload['total_count']} execucoes"
                ),
            }
        )
        return context


class ExecutionDetailView(LoginRequiredMixin, TemplateView):
    template_name = "executions/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = ExecutionsService()

        execution_id = self.kwargs["execution_id"]
        payload = service.get_execution_detail(execution_id)
        if not payload["found"] or payload["execution"] is None:
            raise Http404("Execucao nao encontrada.")

        execution = payload["execution"]
        context.update(
            {
                "page_title": f"Execucao {execution['id']}",
                "active_menu": "execucoes",
                "execution": execution,
                "integration_source": payload["source"],
                "integration_warnings": payload["warnings"],
                "integration_limitation": payload["limitation_message"],
            }
        )
        return context
