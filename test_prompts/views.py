from __future__ import annotations

import base64
import binascii
import logging
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import FormView, ListView, TemplateView

from core.services.automation_prompts_execution_service import (
    AutomationPromptsExecutionService,
    AutomationPromptsExecutionServiceError,
    PromptTestExecutionStartItem,
    PromptTestExecutionResultItem,
    PromptTestExecutionStatusItem,
)
from test_automations.models import TestAutomation

from .forms import TestPromptExecutionForm, TestPromptForm
from .models import TestPrompt, TestPromptExecution

logger = logging.getLogger(__name__)


def _execution_status_meta(status: str) -> dict[str, str]:
    table = {
        "queued": {"label": "Na fila", "css_class": "status-neutral"},
        "pending": {"label": "Pendente", "css_class": "status-neutral"},
        "running": {"label": "Em andamento", "css_class": "status-warning"},
        "processing": {"label": "Processando", "css_class": "status-warning"},
        "completed": {"label": "Concluída", "css_class": "status-success"},
        "failed": {"label": "Falhou", "css_class": "status-danger"},
    }
    normalized = str(status or "").strip().lower()
    return table.get(normalized, {"label": normalized or "Desconhecido", "css_class": "status-neutral"})


def _execution_status_message(*, status: str, error_message: str = "", explicit_message: str = "") -> str:
    explicit = str(explicit_message or "").strip()
    if explicit:
        return explicit
    normalized = str(status or "").strip().lower()
    if normalized in {"queued", "pending"}:
        return "Preparando execução de teste."
    if normalized in {"running", "processing"}:
        return "Execução em andamento."
    if normalized == "completed":
        return "Execução concluída. Resultado pronto."
    if normalized == "failed":
        return error_message or "A execução falhou."
    return "Status da execução atualizado."


def _is_terminal_status(status: str) -> bool:
    normalized = str(status or "").strip().lower()
    return normalized in {"completed", "failed"}


def _resolve_progress_percent(*, status: str, explicit_progress: int | None) -> int:
    if explicit_progress is not None:
        return max(0, min(100, int(explicit_progress)))
    normalized = str(status or "").strip().lower()
    if normalized in {"completed", "failed"}:
        return 100
    return 0


def _execution_phase_label(phase: str) -> str:
    table = {
        "queued": "Na fila",
        "preparing_input": "Preparando entrada",
        "validating_file": "Validando arquivo",
        "reading_input": "Lendo arquivo",
        "prompt_build": "Montando processamento",
        "running_model": "Executando modelo",
        "processing_chunks": "Processando conteudo",
        "processing_rows": "Processando linhas",
        "normalizing_output": "Normalizando saída",
        "exporting_result": "Exportando resultado",
        "completed": "Concluido",
        "failed": "Falhou",
    }
    normalized = str(phase or "").strip().lower()
    return table.get(normalized, normalized or "-")


def _map_remote_status_to_local(remote_status: str) -> str:
    normalized = str(remote_status or "").strip().lower()
    if normalized == "queued":
        return TestPromptExecution.STATUS_QUEUED
    if normalized == "running":
        return TestPromptExecution.STATUS_RUNNING
    if normalized == "completed":
        return TestPromptExecution.STATUS_COMPLETED
    if normalized == "failed":
        return TestPromptExecution.STATUS_FAILED
    return TestPromptExecution.STATUS_PENDING


def _execution_has_local_result(execution: TestPromptExecution) -> bool:
    if execution.result_type == TestPromptExecution.RESULT_FILE:
        return bool(execution.output_file_content)
    if execution.result_type == TestPromptExecution.RESULT_TEXT:
        return bool(str(execution.output_text or "").strip())
    return False


def _serialize_execution_file_rows(*, test_prompt_id: int, execution: TestPromptExecution) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    output_file_content = getattr(execution, "output_file_content", None)
    if execution.result_type == TestPromptExecution.RESULT_FILE and output_file_content:
        rows.append(
            {
                "id": str(execution.id),
                "file_type": "resultado",
                "file_name": execution.output_file_name or f"resultado_{execution.id}.bin",
                "file_size": int(execution.output_file_size or 0),
                "file_size_display": _format_file_size(int(execution.output_file_size or 0)),
                "mime_type": execution.output_file_mime_type or "application/octet-stream",
                "download_url": reverse(
                    "test_prompts:execution_output_download",
                    kwargs={"pk": test_prompt_id, "execution_id": str(execution.id)},
                ),
            }
        )
    debug_file_content = getattr(execution, "debug_file_content", None)
    if debug_file_content:
        rows.append(
            {
                "id": str(execution.id),
                "file_type": "debug",
                "file_name": getattr(execution, "debug_file_name", "") or f"debug_{execution.id}.bin",
                "file_size": int(getattr(execution, "debug_file_size", 0) or 0),
                "file_size_display": _format_file_size(int(getattr(execution, "debug_file_size", 0) or 0)),
                "mime_type": getattr(execution, "debug_file_mime_type", "") or "application/octet-stream",
                "download_url": (
                    reverse(
                        "test_prompts:execution_output_download",
                        kwargs={"pk": test_prompt_id, "execution_id": str(execution.id)},
                    )
                    + "?kind=debug"
                ),
            }
        )
    return rows


def _format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < (1024 * 1024):
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < (1024 * 1024 * 1024):
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _load_test_automations(*, active_only: bool = True) -> list[TestAutomation]:
    queryset = TestAutomation.objects.all().order_by("name")
    if active_only:
        queryset = queryset.filter(is_active=True)
    return list(queryset)


def _build_automation_choices(automations: list[TestAutomation]) -> list[tuple[UUID, str]]:
    choices: list[tuple[UUID, str]] = []
    for item in automations:
        credential_label = item.credential_name or "credencial ativa"
        label = f"{item.name} ({item.provider_slug} / {item.model_slug} / {credential_label})"
        choices.append((item.id, label))
    return choices


def _resolve_selected_test_automation(raw_value: str | UUID | None) -> TestAutomation | None:
    raw = str(raw_value or "").strip()
    if not raw:
        return None
    try:
        automation_id = UUID(raw)
    except ValueError:
        return None
    return TestAutomation.objects.filter(pk=automation_id, is_active=True).first()


def _decode_base64_file(raw_payload: str | None) -> bytes | None:
    raw_base64 = str(raw_payload or "").strip()
    if not raw_base64:
        return None
    try:
        return base64.b64decode(raw_base64)
    except (ValueError, binascii.Error):
        return None


def _decode_output_file(payload: PromptTestExecutionResultItem) -> bytes | None:
    return _decode_base64_file(payload.output_file_base64)


def _apply_remote_snapshot_to_execution(
    *,
    execution: TestPromptExecution,
    snapshot: PromptTestExecutionStatusItem,
) -> None:
    execution.remote_status = snapshot.status
    execution.remote_phase = snapshot.phase
    execution.remote_progress_percent = int(snapshot.progress_percent or 0)
    execution.remote_status_message = snapshot.status_message or ""
    execution.remote_result_ready = bool(snapshot.result_ready)
    execution.remote_error_message = snapshot.error_message or ""
    execution.remote_last_checked_at = timezone.now()
    execution.status = _map_remote_status_to_local(snapshot.status)
    if snapshot.status == "failed":
        execution.error_message = snapshot.error_message or execution.error_message


def _persist_remote_execution_result(
    *,
    execution: TestPromptExecution,
    result: PromptTestExecutionResultItem,
) -> None:
    output_file_content = _decode_output_file(result)
    debug_file_content = _decode_base64_file(result.debug_file_base64)
    execution.status = TestPromptExecution.STATUS_COMPLETED
    execution.result_type = (
        TestPromptExecution.RESULT_FILE
        if result.result_type == TestPromptExecution.RESULT_FILE
        else TestPromptExecution.RESULT_TEXT
    )
    execution.output_text = result.output_text or ""
    execution.output_file_content = output_file_content
    execution.output_file_name = result.output_file_name or ""
    execution.output_file_mime_type = result.output_file_mime_type or ""
    execution.output_file_checksum = result.output_file_checksum or ""
    execution.output_file_size = int(result.output_file_size or 0)
    execution.debug_file_content = debug_file_content
    execution.debug_file_name = result.debug_file_name or ""
    execution.debug_file_mime_type = result.debug_file_mime_type or ""
    execution.debug_file_checksum = result.debug_file_checksum or ""
    execution.debug_file_size = int(result.debug_file_size or 0)
    execution.provider_calls = int(result.provider_calls or 0)
    execution.input_tokens = int(result.input_tokens or 0)
    execution.output_tokens = int(result.output_tokens or 0)
    execution.estimated_cost = result.estimated_cost or "0"
    execution.duration_ms = int(result.duration_ms or 0)
    execution.error_message = ""


def _sync_execution_with_remote(
    *,
    execution: TestPromptExecution,
    service: AutomationPromptsExecutionService | None = None,
) -> PromptTestExecutionStatusItem | None:
    remote_execution_id = getattr(execution, "remote_execution_id", None)
    if remote_execution_id is None:
        return None
    service = service or AutomationPromptsExecutionService()
    try:
        snapshot = service.get_test_prompt_execution_status(execution_id=remote_execution_id)
    except AutomationPromptsExecutionServiceError as exc:
        logger.warning(
            "Failed to fetch remote prompt-test execution status.",
            extra={
                "execution_id": str(execution.id),
                "remote_execution_id": str(remote_execution_id),
                "phase": "test_prompt.execution.status_sync_failed",
            },
            exc_info=exc,
        )
        return None

    _apply_remote_snapshot_to_execution(execution=execution, snapshot=snapshot)
    should_fetch_result = (
        snapshot.status == "completed"
        and snapshot.result_ready
        and not _execution_has_local_result(execution)
    )
    if should_fetch_result:
        try:
            result = service.get_test_prompt_execution_result(execution_id=remote_execution_id)
        except AutomationPromptsExecutionServiceError as exc:
            logger.warning(
                "Failed to fetch remote prompt-test execution result.",
                extra={
                    "execution_id": str(execution.id),
                    "remote_execution_id": str(remote_execution_id),
                    "phase": "test_prompt.execution.result_sync_failed",
                },
                exc_info=exc,
            )
        else:
            _persist_remote_execution_result(execution=execution, result=result)

    execution.save()
    return snapshot


class TestPromptListView(LoginRequiredMixin, ListView):
    template_name = "test_prompts/list.html"
    context_object_name = "test_prompts"
    model = TestPrompt

    def get_queryset(self):
        queryset = TestPrompt.objects.all().order_by("-updated_at", "name")
        search_query = str(self.request.GET.get("q") or "").strip()
        selected_status = str(self.request.GET.get("status") or "").strip().lower()

        if search_query:
            queryset = queryset.filter(name__icontains=search_query)
        if selected_status == "ativo":
            queryset = queryset.filter(is_active=True)
        elif selected_status == "inativo":
            queryset = queryset.filter(is_active=False)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prompts = context.get("test_prompts") or []
        context.update(
            {
                "page_title": "Prompts de teste",
                "page_subtitle": "CRUD local de prompts de teste usado apenas pela interface.",
                "active_menu": "prompts_teste",
                "integration_source": "local",
                "integration_warnings": [],
                "test_automations_count": TestAutomation.objects.filter(is_active=True).count(),
                "search_query": str(self.request.GET.get("q") or "").strip(),
                "selected_status": str(self.request.GET.get("status") or "").strip().lower(),
                "total_count": TestPrompt.objects.count(),
                "filtered_count": len(prompts),
                "list_counter_label": f"{len(prompts)} prompt(s) de teste",
            }
        )
        return context


class TestPromptCreateView(LoginRequiredMixin, FormView):
    template_name = "test_prompts/form.html"
    form_class = TestPromptForm
    test_automations: list[TestAutomation]

    def dispatch(self, request, *args, **kwargs):
        self.test_automations = _load_test_automations(active_only=True)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["automation_choices"] = _build_automation_choices(self.test_automations)
        selected_automation = str(self.request.POST.get("automation_id") or self.request.GET.get("automation_id") or "").strip()
        kwargs["selected_automation"] = selected_automation or None
        return kwargs

    def form_valid(self, form):
        selected_automation = _resolve_selected_test_automation(form.cleaned_data.get("automation_id"))
        if selected_automation is None:
            form.add_error("automation_id", "Selecione uma automação de teste ativa e válida.")
            return self.form_invalid(form)

        TestPrompt.objects.create(
            name=form.cleaned_data["name"],
            automation_id=selected_automation.id,
            prompt_text=form.cleaned_data["prompt_text"],
            notes=form.cleaned_data.get("notes") or "",
            is_active=bool(form.cleaned_data.get("is_active", False)),
            created_by=self.request.user if self.request.user.is_authenticated else None,
            updated_by=self.request.user if self.request.user.is_authenticated else None,
        )
        messages.success(self.request, "Prompt de teste criado com sucesso.")
        return redirect("test_prompts:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Novo prompt de teste",
                "form_title": "Novo prompt de teste",
                "form_subtitle": "Prompt experimental local. Não altera prompt oficial.",
                "active_menu": "prompts_teste",
                "submit_label": "Salvar prompt de teste",
                "is_editing": False,
                "test_automations_count": len(getattr(self, "test_automations", [])),
            }
        )
        return context


class TestPromptUpdateView(LoginRequiredMixin, FormView):
    template_name = "test_prompts/form.html"
    form_class = TestPromptForm
    test_prompt: TestPrompt
    test_automations: list[TestAutomation]

    def dispatch(self, request, *args, **kwargs):
        self.test_prompt = get_object_or_404(TestPrompt, pk=kwargs["pk"])
        self.test_automations = _load_test_automations(active_only=True)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {
            "name": self.test_prompt.name,
            "automation_id": str(self.test_prompt.automation_id or ""),
            "prompt_text": self.test_prompt.prompt_text,
            "notes": self.test_prompt.notes,
            "is_active": self.test_prompt.is_active,
        }

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["automation_choices"] = _build_automation_choices(self.test_automations)
        selected_automation = str(
            self.request.POST.get("automation_id")
            or self.request.GET.get("automation_id")
            or self.test_prompt.automation_id
            or ""
        ).strip()
        kwargs["selected_automation"] = selected_automation or None
        return kwargs

    def form_valid(self, form):
        selected_automation = _resolve_selected_test_automation(form.cleaned_data.get("automation_id"))
        if selected_automation is None:
            form.add_error("automation_id", "Selecione uma automação de teste ativa e válida.")
            return self.form_invalid(form)

        self.test_prompt.name = form.cleaned_data["name"]
        self.test_prompt.automation_id = selected_automation.id
        self.test_prompt.prompt_text = form.cleaned_data["prompt_text"]
        self.test_prompt.notes = form.cleaned_data.get("notes") or ""
        self.test_prompt.is_active = bool(form.cleaned_data.get("is_active", False))
        self.test_prompt.updated_by = self.request.user if self.request.user.is_authenticated else None
        self.test_prompt.save(
            update_fields=[
                "name",
                "automation_id",
                "prompt_text",
                "notes",
                "is_active",
                "updated_by",
                "updated_at",
            ]
        )
        messages.success(self.request, "Prompt de teste atualizado com sucesso.")
        return redirect("test_prompts:detail", pk=self.test_prompt.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Editar prompt de teste",
                "form_title": "Editar prompt de teste",
                "form_subtitle": "Prompt experimental local. Não altera prompt oficial.",
                "active_menu": "prompts_teste",
                "submit_label": "Salvar alterações",
                "is_editing": True,
                "object": self.test_prompt,
                "test_automations_count": len(getattr(self, "test_automations", [])),
            }
        )
        return context


class TestPromptDetailView(LoginRequiredMixin, TemplateView):
    template_name = "test_prompts/detail.html"
    test_prompt: TestPrompt
    selected_automation: TestAutomation | None = None

    def dispatch(self, request, *args, **kwargs):
        self.test_prompt = get_object_or_404(TestPrompt, pk=kwargs["pk"])
        self.selected_automation = None
        if self.test_prompt.automation_id is not None:
            self.selected_automation = TestAutomation.objects.filter(pk=self.test_prompt.automation_id).first()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        recent_executions = list(self.test_prompt.executions.all()[:10])
        context.update(
            {
                "page_title": self.test_prompt.name,
                "active_menu": "prompts_teste",
                "test_prompt": self.test_prompt,
                "selected_automation": self.selected_automation,
                "has_valid_automation": self.selected_automation is not None and bool(self.selected_automation.is_active),
                "integration_source": "local",
                "integration_warnings": [],
                "recent_executions": recent_executions,
            }
        )
        return context


class TestPromptExecutionCreateView(LoginRequiredMixin, FormView):
    template_name = "test_prompts/execute.html"
    form_class = TestPromptExecutionForm
    test_prompt: TestPrompt
    linked_automation: TestAutomation | None = None

    def dispatch(self, request, *args, **kwargs):
        self.test_prompt = get_object_or_404(TestPrompt, pk=kwargs["pk"])
        self.linked_automation = _resolve_selected_test_automation(self.test_prompt.automation_id)
        if self.linked_automation is None:
            messages.error(
                request,
                "Este prompt de teste não possui automação vinculada ativa. Vincule uma automação antes de executar.",
            )
            return redirect("test_prompts:edit", pk=self.test_prompt.pk)
        return super().dispatch(request, *args, **kwargs)

    def _build_execution_record(
        self,
        *,
        automation: TestAutomation,
        uploaded_file,
        remote_start: PromptTestExecutionStartItem,
        status: str,
        result_type: str,
        output_text: str = "",
        output_file_content: bytes | None = None,
        output_file_name: str = "",
        output_file_mime_type: str = "",
        output_file_checksum: str = "",
        output_file_size: int = 0,
        debug_file_content: bytes | None = None,
        debug_file_name: str = "",
        debug_file_mime_type: str = "",
        debug_file_checksum: str = "",
        debug_file_size: int = 0,
        provider_calls: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost: str = "0",
        duration_ms: int = 0,
        error_message: str = "",
    ) -> TestPromptExecution:
        uploaded_size = getattr(uploaded_file, "size", None)
        if uploaded_size is None:
            try:
                uploaded_size = uploaded_file.tell()
            except Exception:
                uploaded_size = 0
        return TestPromptExecution.objects.create(
            test_prompt=self.test_prompt,
            test_automation_id=automation.id,
            test_automation_name=automation.name,
            provider_id=automation.provider_id,
            model_id=automation.model_id,
            credential_id=automation.credential_id,
            provider_slug=automation.provider_slug,
            model_slug=automation.model_slug,
            credential_name=automation.credential_name,
            prompt_override=self.test_prompt.prompt_text,
            request_file_name=str(getattr(uploaded_file, "name", "") or ""),
            request_file_mime_type=str(getattr(uploaded_file, "content_type", "") or ""),
            request_file_size=int(uploaded_size or 0),
            remote_execution_id=remote_start.execution_id,
            remote_status=remote_start.status,
            remote_phase=remote_start.phase,
            remote_progress_percent=int(remote_start.progress_percent or 0),
            remote_status_message=remote_start.status_message or "",
            remote_result_ready=bool(remote_start.is_terminal),
            remote_error_message="",
            remote_last_checked_at=timezone.now(),
            status=status,
            result_type=result_type,
            output_text=output_text,
            output_file_name=output_file_name,
            output_file_mime_type=output_file_mime_type,
            output_file_size=output_file_size,
            output_file_content=output_file_content,
            output_file_checksum=output_file_checksum,
            debug_file_name=debug_file_name,
            debug_file_mime_type=debug_file_mime_type,
            debug_file_size=debug_file_size,
            debug_file_content=debug_file_content,
            debug_file_checksum=debug_file_checksum,
            provider_calls=provider_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            duration_ms=duration_ms,
            error_message=error_message,
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )

    def form_valid(self, form):
        automation = self.linked_automation
        if automation is None:
            form.add_error(None, "Automação vinculada não encontrada ou inativa para este prompt.")
            return self.form_invalid(form)

        uploaded_file = form.cleaned_data["request_file"]
        service = AutomationPromptsExecutionService()
        try:
            remote_start = service.start_test_prompt_execution(
                provider_id=automation.provider_id,
                model_id=automation.model_id,
                credential_id=automation.credential_id,
                uploaded_file=uploaded_file,
                prompt_override=self.test_prompt.prompt_text,
                output_type=str(getattr(automation, "output_type", "") or "").strip() or None,
                result_parser=str(getattr(automation, "result_parser", "") or "").strip() or None,
                result_formatter=str(getattr(automation, "result_formatter", "") or "").strip() or None,
                output_schema=getattr(automation, "output_schema", None),
                debug_enabled=bool(getattr(automation, "debug_enabled", False)),
            )
        except AutomationPromptsExecutionServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        execution = self._build_execution_record(
            automation=automation,
            uploaded_file=uploaded_file,
            remote_start=remote_start,
            status=_map_remote_status_to_local(remote_start.status),
            result_type=TestPromptExecution.RESULT_TEXT,
            error_message="",
        )

        messages.success(self.request, "Execucao de teste iniciada. Acompanhe o progresso na tela de status.")
        return redirect(
            "test_prompts:execution_detail",
            pk=self.test_prompt.pk,
            execution_id=str(execution.id),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Executar prompt de teste",
                "active_menu": "prompts_teste",
                "test_prompt": self.test_prompt,
                "selected_automation": self.linked_automation,
                "integration_source": "local",
                "integration_warnings": [],
            }
        )
        return context


class TestPromptExecutionDetailView(LoginRequiredMixin, TemplateView):
    template_name = "test_prompts/execution_detail.html"
    test_prompt: TestPrompt
    execution: TestPromptExecution

    def dispatch(self, request, *args, **kwargs):
        self.test_prompt = get_object_or_404(TestPrompt, pk=kwargs["pk"])
        try:
            execution_uuid = UUID(str(kwargs["execution_id"]))
        except ValueError as exc:
            raise Http404("ID de execução inválido.") from exc
        self.execution = get_object_or_404(TestPromptExecution, pk=execution_uuid, test_prompt=self.test_prompt)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        snapshot = _sync_execution_with_remote(execution=self.execution)
        status_source = (
            snapshot.status
            if snapshot is not None
            else (self.execution.remote_status or self.execution.status)
        )
        phase_source = (
            snapshot.phase
            if snapshot is not None
            else str(self.execution.remote_phase or "").strip().lower()
        )
        progress_source = (
            snapshot.progress_percent
            if snapshot is not None
            else (
                self.execution.remote_progress_percent
                if self.execution.remote_execution_id is not None or str(self.execution.remote_status or "").strip()
                else None
            )
        )
        status_meta = _execution_status_meta(status_source)
        is_terminal = _is_terminal_status(status_source)
        progress_percent = _resolve_progress_percent(status=status_source, explicit_progress=progress_source)
        status_message = _execution_status_message(
            status=status_source,
            error_message=self.execution.error_message or self.execution.remote_error_message,
            explicit_message=(
                snapshot.status_message
                if snapshot is not None
                else self.execution.remote_status_message
            ),
        )
        output_download_url = None
        if self.execution.result_type == TestPromptExecution.RESULT_FILE and self.execution.output_file_content:
            output_download_url = reverse(
                "test_prompts:execution_output_download",
                kwargs={"pk": self.test_prompt.pk, "execution_id": str(self.execution.id)},
            )
        file_rows = _serialize_execution_file_rows(test_prompt_id=self.test_prompt.pk, execution=self.execution)
        output_file_row = next((item for item in file_rows if item.get("file_type") == "resultado"), None)
        debug_file_row = next((item for item in file_rows if item.get("file_type") == "debug"), None)
        context.update(
            {
                "page_title": f"Execucao de teste {self.execution.id}",
                "active_menu": "prompts_teste",
                "test_prompt": self.test_prompt,
                "execution": self.execution,
                "status_label": status_meta["label"],
                "status_css_class": status_meta["css_class"],
                "status_message": status_message,
                "is_terminal": is_terminal,
                "progress_percent": progress_percent,
                "phase": phase_source,
                "phase_label": _execution_phase_label(phase_source),
                "processed_rows": (
                    snapshot.processed_rows
                    if snapshot is not None
                    else None
                ),
                "total_rows": (
                    snapshot.total_rows
                    if snapshot is not None
                    else None
                ),
                "current_row": (
                    snapshot.current_row
                    if snapshot is not None
                    else None
                ),
                "status_endpoint_url": reverse(
                    "test_prompts:execution_status",
                    kwargs={"pk": self.test_prompt.pk, "execution_id": str(self.execution.id)},
                ),
                "integration_source": "local",
                "integration_warnings": [],
                "output_download_url": output_download_url,
                "debug_download_url": debug_file_row.get("download_url") if isinstance(debug_file_row, dict) else None,
                "file_rows": file_rows,
                "file_row": output_file_row,
                "request_file_size_display": _format_file_size(int(self.execution.request_file_size or 0)),
                "output_file_size_display": _format_file_size(int(self.execution.output_file_size or 0)),
                "debug_file_size_display": _format_file_size(int(getattr(self.execution, "debug_file_size", 0) or 0)),
            }
        )
        return context


class TestPromptExecutionStatusView(LoginRequiredMixin, View):
    def get(self, request, pk: int, execution_id: str):
        test_prompt = get_object_or_404(TestPrompt, pk=pk)
        try:
            execution_uuid = UUID(str(execution_id))
        except ValueError:
            return JsonResponse({"ok": False, "error": "ID de execução inválido."}, status=400)

        execution = get_object_or_404(TestPromptExecution, pk=execution_uuid, test_prompt=test_prompt)
        snapshot = _sync_execution_with_remote(execution=execution)
        status_source = snapshot.status if snapshot is not None else (execution.remote_status or execution.status)
        phase_source = snapshot.phase if snapshot is not None else (execution.remote_phase or "")
        progress_source = (
            snapshot.progress_percent
            if snapshot is not None
            else (
                execution.remote_progress_percent
                if execution.remote_execution_id is not None or str(execution.remote_status or "").strip()
                else None
            )
        )
        status_meta = _execution_status_meta(status_source)
        is_terminal = _is_terminal_status(status_source)
        progress_percent = _resolve_progress_percent(status=status_source, explicit_progress=progress_source)
        status_message = _execution_status_message(
            status=status_source,
            error_message=execution.error_message or execution.remote_error_message,
            explicit_message=(snapshot.status_message if snapshot is not None else execution.remote_status_message),
        )
        file_rows = _serialize_execution_file_rows(test_prompt_id=test_prompt.pk, execution=execution)
        output_file_row = next((item for item in file_rows if item.get("file_type") == "resultado"), None)
        debug_file_row = next((item for item in file_rows if item.get("file_type") == "debug"), None)
        output_download_url = output_file_row["download_url"] if output_file_row else None
        debug_download_url = debug_file_row["download_url"] if debug_file_row else None

        return JsonResponse(
            {
                "ok": True,
                "execution_id": str(execution.id),
                "status": status_source,
                "phase": phase_source,
                "phase_label": _execution_phase_label(phase_source),
                "status_label": status_meta["label"],
                "status_css_class": status_meta["css_class"],
                "status_message": status_message,
                "progress_percent": progress_percent,
                "is_terminal": is_terminal,
                "error_message": execution.error_message or execution.remote_error_message,
                "result_ready": bool(snapshot.result_ready) if snapshot is not None else bool(execution.remote_result_ready),
                "processed_rows": snapshot.processed_rows if snapshot is not None else None,
                "total_rows": snapshot.total_rows if snapshot is not None else None,
                "current_row": snapshot.current_row if snapshot is not None else None,
                "result_type": execution.result_type,
                "output_text": execution.output_text,
                "output_file_name": execution.output_file_name,
                "output_file_mime_type": execution.output_file_mime_type,
                "output_file_size_display": _format_file_size(int(execution.output_file_size or 0)),
                "output_download_url": output_download_url,
                "debug_file_name": getattr(execution, "debug_file_name", ""),
                "debug_file_mime_type": getattr(execution, "debug_file_mime_type", ""),
                "debug_file_size_display": _format_file_size(int(getattr(execution, "debug_file_size", 0) or 0)),
                "debug_download_url": debug_download_url,
                "file_rows": file_rows,
                "file_row": output_file_row,
            }
        )


class TestPromptExecutionOutputDownloadView(LoginRequiredMixin, View):
    def get(self, request, pk: int, execution_id: str):
        test_prompt = get_object_or_404(TestPrompt, pk=pk)
        try:
            execution_uuid = UUID(str(execution_id))
        except ValueError:
            messages.error(request, "ID de execução inválido para download.")
            return redirect("test_prompts:detail", pk=test_prompt.pk)

        execution = get_object_or_404(TestPromptExecution, pk=execution_uuid, test_prompt=test_prompt)
        output_kind = str(request.GET.get("kind") or "output").strip().lower()
        if output_kind == "debug":
            content = getattr(execution, "debug_file_content", None)
            mime_type = getattr(execution, "debug_file_mime_type", "") or "application/octet-stream"
            filename = getattr(execution, "debug_file_name", "") or f"debug_{execution.id}.bin"
            checksum = getattr(execution, "debug_file_checksum", "")
        else:
            content = execution.output_file_content
            mime_type = execution.output_file_mime_type or "application/octet-stream"
            filename = execution.output_file_name or f"{execution.id}.bin"
            checksum = execution.output_file_checksum

        if not content:
            messages.error(request, "Esta execução não possui o arquivo solicitado salvo.")
            return redirect("test_prompts:execution_detail", pk=test_prompt.pk, execution_id=str(execution.id))

        response = HttpResponse(
            content,
            content_type=mime_type,
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        if checksum:
            response["X-File-Checksum"] = checksum
        return response


class TestPromptDeleteView(LoginRequiredMixin, TemplateView):
    template_name = "test_prompts/delete.html"
    test_prompt: TestPrompt

    def dispatch(self, request, *args, **kwargs):
        self.test_prompt = get_object_or_404(TestPrompt, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        prompt_name = self.test_prompt.name
        self.test_prompt.delete()
        messages.success(request, f'Prompt de teste "{prompt_name}" excluido com sucesso.')
        return redirect("test_prompts:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Excluir prompt de teste",
                "active_menu": "prompts_teste",
                "test_prompt": self.test_prompt,
            }
        )
        return context


@login_required
@require_POST
def test_prompt_toggle_status(request, pk: int):
    prompt = get_object_or_404(TestPrompt, pk=pk)
    prompt.is_active = not prompt.is_active
    prompt.updated_by = request.user if request.user.is_authenticated else None
    prompt.save(update_fields=["is_active", "updated_by", "updated_at"])
    if prompt.is_active:
        messages.success(request, "Prompt de teste ativado.")
    else:
        messages.success(request, "Prompt de teste desativado.")
    return redirect("test_prompts:list")


@login_required
@require_POST
def test_prompt_duplicate(request, pk: int):
    source = get_object_or_404(TestPrompt, pk=pk)
    duplicated = TestPrompt.objects.create(
        name=f"{source.name} (copia)",
        automation_id=source.automation_id,
        prompt_text=source.prompt_text,
        notes=source.notes,
        is_active=False,
        created_by=request.user if request.user.is_authenticated else None,
        updated_by=request.user if request.user.is_authenticated else None,
    )
    messages.success(request, "Prompt de teste duplicado. Revise antes de executar.")
    return redirect("test_prompts:edit", pk=duplicated.pk)
