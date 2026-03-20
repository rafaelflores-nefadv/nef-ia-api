from __future__ import annotations

from uuid import UUID

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from core.services.automation_prompts_execution_service import (
    AutomationExecutionFileItem,
    AutomationExecutionStatusItem,
    AutomationPromptsExecutionService,
    AutomationPromptsExecutionServiceError,
)

from .forms import AutomationExecutionForm


def _execution_status_meta(status: str) -> dict[str, str]:
    table = {
        "queued": {"label": "Na fila", "css_class": "status-neutral"},
        "pending": {"label": "Pendente", "css_class": "status-neutral"},
        "processing": {"label": "Processando", "css_class": "status-warning"},
        "generating_output": {"label": "Gerando resultado", "css_class": "status-warning"},
        "completed": {"label": "Concluida", "css_class": "status-success"},
        "failed": {"label": "Falhou", "css_class": "status-danger"},
    }
    normalized = str(status or "").strip().lower()
    return table.get(normalized, {"label": normalized or "Desconhecido", "css_class": "status-neutral"})


def _is_terminal_status(status: str) -> bool:
    normalized = str(status or "").strip().lower()
    return normalized in {"completed", "failed"}


def _format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < (1024 * 1024):
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < (1024 * 1024 * 1024):
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class AutomationPromptListView(LoginRequiredMixin, ListView):
    template_name = "prompts/list.html"
    context_object_name = "automations"

    def get_queryset(self):
        payload = AutomationPromptsExecutionService().list_automations_runtime()
        self.integration_source = payload["source"]
        self.integration_warnings = payload["warnings"]
        return payload["items"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items = context.get("automations") or []
        context.update(
            {
                "page_title": "Prompts de automacao",
                "page_subtitle": "Fonte oficial via FastAPI e banco compartilhado (automations + automation_prompts).",
                "active_menu": "prompts",
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
                "total_count": len(items),
                "list_counter_label": f"{len(items)} automacao(oes) carregada(s)",
            }
        )
        return context


class AutomationExecutionCreateView(LoginRequiredMixin, FormView):
    template_name = "prompts/form.html"
    form_class = AutomationExecutionForm
    selected_automation = None

    def _load_runtime_payload(self) -> dict:
        payload = AutomationPromptsExecutionService().list_automations_runtime()
        self.integration_source = payload["source"]
        self.integration_warnings = payload["warnings"]
        return payload

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        payload = self._load_runtime_payload()
        items = payload.get("items", [])
        selected_automation = str(self.request.GET.get("automation") or "").strip()
        if self.request.method == "POST":
            selected_automation = str(self.request.POST.get("automation") or selected_automation).strip()

        choices = [
            (
                item.automation_id,
                f"{item.automation_name} ({item.automation_id})",
            )
            for item in items
        ]
        kwargs["automation_choices"] = choices
        kwargs["selected_automation"] = selected_automation or None

        self.selected_automation = None
        if selected_automation:
            for item in items:
                if str(item.automation_id) == selected_automation:
                    self.selected_automation = item
                    break
        if self.selected_automation is not None:
            service = AutomationPromptsExecutionService()
            try:
                self.selected_automation = service.get_automation_runtime(
                    automation_id=self.selected_automation.automation_id,
                )
            except AutomationPromptsExecutionServiceError as exc:
                existing_warnings = list(getattr(self, "integration_warnings", []) or [])
                warning_message = str(exc).strip()
                if warning_message and warning_message not in existing_warnings:
                    existing_warnings.append(warning_message)
                    self.integration_warnings = existing_warnings
        return kwargs

    def form_valid(self, form):
        automation_value = str(form.cleaned_data["automation"] or "").strip()
        try:
            automation_id = UUID(automation_value)
        except ValueError:
            form.add_error("automation", "Automacao invalida.")
            return self.form_invalid(form)

        uploaded_file = form.cleaned_data["request_file"]
        service = AutomationPromptsExecutionService()
        try:
            result = service.start_execution(
                automation_id=automation_id,
                uploaded_file=uploaded_file,
            )
        except AutomationPromptsExecutionServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(
            self.request,
            "Execucao real iniciada com sucesso. Acompanhe o status no detalhe.",
        )
        return redirect("prompts:execution_detail", execution_id=str(result.execution_id))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Executar automacao",
                "form_title": "Executar automacao",
                "form_subtitle": "Fluxo oficial: upload de arquivo + criacao de execution real.",
                "active_menu": "prompts",
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
                "selected_automation": getattr(self, "selected_automation", None),
                "submit_label": "Subir arquivo e executar",
            }
        )
        return context


class AutomationExecutionDetailView(LoginRequiredMixin, TemplateView):
    template_name = "prompts/execution_detail.html"
    execution_status: AutomationExecutionStatusItem | None = None
    execution_files: list[AutomationExecutionFileItem] = []

    def _parse_execution_id(self) -> UUID:
        execution_id_raw = str(self.kwargs.get("execution_id") or "").strip()
        try:
            return UUID(execution_id_raw)
        except ValueError as exc:
            raise Http404("ID de execucao invalido.") from exc

    def _load_execution(self, *, execution_id: UUID) -> None:
        service = AutomationPromptsExecutionService()
        self.execution_status = service.get_execution_status(execution_id=execution_id)
        self.integration_source = "api"
        self.integration_warnings = []
        try:
            self.execution_files = service.list_execution_files(execution_id=execution_id)
        except AutomationPromptsExecutionServiceError as exc:
            self.execution_files = []
            self.integration_source = "api_partial"
            self.integration_warnings = [str(exc)]

    def get(self, request, *args, **kwargs):
        execution_id = self._parse_execution_id()
        try:
            self._load_execution(execution_id=execution_id)
        except AutomationPromptsExecutionServiceError as exc:
            messages.error(
                request,
                f"Nao foi possivel carregar a execucao real: {exc}",
            )
            return redirect("prompts:list")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        execution = self.execution_status
        files = self.execution_files
        if execution is None:
            execution = AutomationExecutionStatusItem(
                execution_id=UUID("00000000-0000-0000-0000-000000000000"),
                analysis_request_id=UUID("00000000-0000-0000-0000-000000000000"),
                automation_id=UUID("00000000-0000-0000-0000-000000000000"),
                request_file_id=None,
                request_file_name=None,
                status="unknown",
                progress=None,
                started_at=None,
                finished_at=None,
                error_message="",
                created_at=None,
                checked_at=None,
            )
        status_meta = _execution_status_meta(execution.status)
        is_terminal = _is_terminal_status(execution.status)

        file_rows = []
        for file_item in files:
            file_rows.append(
                {
                    "id": file_item.id,
                    "file_type": file_item.file_type,
                    "file_name": file_item.file_name,
                    "file_size": file_item.file_size,
                    "file_size_display": _format_file_size(file_item.file_size),
                    "created_at": file_item.created_at,
                    "mime_type": file_item.mime_type or "-",
                    "download_url": reverse("prompts:execution_file_download", kwargs={"file_id": str(file_item.id)}),
                }
            )

        context.update(
            {
                "page_title": f"Execucao real {execution.execution_id}",
                "active_menu": "prompts",
                "execution": execution,
                "status_label": status_meta["label"],
                "status_css_class": status_meta["css_class"],
                "is_terminal": is_terminal,
                "auto_refresh_seconds": 4 if not is_terminal else 0,
                "file_rows": file_rows,
                "integration_source": getattr(self, "integration_source", "api"),
                "integration_warnings": getattr(self, "integration_warnings", []),
            }
        )
        return context


class AutomationExecutionFileDownloadView(LoginRequiredMixin, View):
    def get(self, request, file_id: str):
        try:
            file_uuid = UUID(str(file_id))
        except ValueError:
            messages.error(request, "ID de arquivo invalido para download.")
            return redirect("prompts:list")

        payload = AutomationPromptsExecutionService().download_execution_file(file_id=file_uuid)
        if not payload.get("ok"):
            messages.error(
                request,
                str(payload.get("error") or "Falha ao baixar arquivo remoto da execucao."),
            )
            referer = str(request.META.get("HTTP_REFERER") or "").strip()
            if referer:
                return redirect(referer)
            return redirect("prompts:list")

        content = payload.get("content") or b""
        filename = str(payload.get("filename") or f"{file_uuid}.bin")
        content_type = str(payload.get("content_type") or "application/octet-stream")
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        checksum = payload.get("checksum")
        if checksum:
            response["X-File-Checksum"] = str(checksum)
        return response
