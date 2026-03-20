from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView

from core.services.executions_service import ExecutionsService


PERIOD_OPTIONS = [
    ("", "Todos os períodos"),
    ("24h", "Últimas 24 horas"),
    ("7d", "Últimos 7 dias"),
    ("30d", "Últimos 30 dias"),
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
                "page_title": "Execuções",
                "page_subtitle": "Visão administrativa das execuções da plataforma.",
                "active_menu": "execucoes",
                "executions": payload["items"],
                "status_options": [
                    ("", "Todos os status"),
                    ("pendente", "Pendente"),
                    ("em_andamento", "Em andamento"),
                    ("concluida", "Concluída"),
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
                    f"Exibindo {payload['filtered_count']} de {payload['total_count']} execuções"
                ),
            }
        )
        return context


class ExecutionDetailView(LoginRequiredMixin, TemplateView):
    template_name = "executions/detail.html"
    execution_payload: dict | None = None

    def get(self, request, *args, **kwargs):
        execution_id = self.kwargs["execution_id"]
        payload = ExecutionsService().get_execution_detail(execution_id)
        if not payload["found"] or payload["execution"] is None:
            messages.error(
                request,
                str(
                    payload.get("limitation_message")
                    or "Execucao nao encontrada na consulta remota da API."
                ),
            )
            return redirect("executions:list")
        self.execution_payload = payload
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payload = self.execution_payload or {}
        execution = payload.get("execution")
        if execution is None:
            execution = {}

        context.update(
            {
                "page_title": f"Execucao {execution.get('id', '-')}",
                "active_menu": "execucoes",
                "execution": execution,
                "integration_source": payload.get("source", "unavailable"),
                "integration_warnings": payload.get("warnings", []),
                "integration_limitation": payload.get("limitation_message"),
            }
        )
        return context
