from __future__ import annotations

from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import FormView, ListView, TemplateView

from core.services.automation_prompts_execution_service import (
    AutomationExecutionFileItem,
    AutomationExecutionStatusItem,
    AutomationPromptsExecutionService,
    AutomationPromptsExecutionServiceError,
    AutomationRuntimeReadItem,
)

from .forms import TestPromptExecutionForm, TestPromptForm
from .models import TestPrompt


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


def _load_automation_runtime_payload() -> tuple[list[AutomationRuntimeReadItem], str, list[str]]:
    payload = AutomationPromptsExecutionService().list_automations_runtime()
    return (
        list(payload.get("items", [])),
        str(payload.get("source") or "unavailable"),
        list(payload.get("warnings") or []),
    )


class TestPromptListView(LoginRequiredMixin, ListView):
    template_name = "test_prompts/list.html"
    context_object_name = "test_prompts"
    model = TestPrompt

    def get_queryset(self):
        queryset = TestPrompt.objects.all().order_by("-updated_at", "name")
        search_query = str(self.request.GET.get("q") or "").strip()
        selected_status = str(self.request.GET.get("status") or "").strip().lower()
        selected_automation = str(self.request.GET.get("automation") or "").strip()

        if search_query:
            queryset = queryset.filter(name__icontains=search_query)
        if selected_status == "ativo":
            queryset = queryset.filter(is_active=True)
        elif selected_status == "inativo":
            queryset = queryset.filter(is_active=False)
        if selected_automation:
            try:
                selected_automation_uuid = UUID(selected_automation)
            except ValueError:
                selected_automation_uuid = None
            if selected_automation_uuid is not None:
                queryset = queryset.filter(automation_id=selected_automation_uuid)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        automations, integration_source, integration_warnings = _load_automation_runtime_payload()
        automation_name_by_id = {str(item.automation_id): item.automation_name for item in automations}

        prompts = context.get("test_prompts") or []
        for prompt in prompts:
            prompt.automation_name = automation_name_by_id.get(str(prompt.automation_id), str(prompt.automation_id))

        context.update(
            {
                "page_title": "Prompts de teste",
                "page_subtitle": "Uso local da interface. Nao altera o prompt oficial da automacao.",
                "active_menu": "prompts_teste",
                "integration_source": integration_source,
                "integration_warnings": integration_warnings,
                "automation_filter_options": [
                    (str(item.automation_id), f"{item.automation_name} ({item.automation_id})")
                    for item in automations
                ],
                "search_query": str(self.request.GET.get("q") or "").strip(),
                "selected_status": str(self.request.GET.get("status") or "").strip().lower(),
                "selected_automation": str(self.request.GET.get("automation") or "").strip(),
                "total_count": TestPrompt.objects.count(),
                "filtered_count": len(prompts),
                "list_counter_label": f"{len(prompts)} prompt(s) de teste",
            }
        )
        return context


class TestPromptCreateView(LoginRequiredMixin, FormView):
    template_name = "test_prompts/form.html"
    form_class = TestPromptForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        automations, integration_source, integration_warnings = _load_automation_runtime_payload()
        self.integration_source = integration_source
        self.integration_warnings = integration_warnings
        kwargs["automation_choices"] = [
            (item.automation_id, f"{item.automation_name} ({item.automation_id})")
            for item in automations
        ]
        return kwargs

    def form_valid(self, form):
        prompt = TestPrompt(
            name=form.cleaned_data["name"],
            automation_id=form.cleaned_data["automation"],
            prompt_text=form.cleaned_data["prompt_text"],
            notes=form.cleaned_data.get("notes") or "",
            is_active=bool(form.cleaned_data.get("is_active", False)),
            created_by=self.request.user if self.request.user.is_authenticated else None,
            updated_by=self.request.user if self.request.user.is_authenticated else None,
        )
        prompt.save()
        messages.success(self.request, "Prompt de teste criado com sucesso.")
        return redirect("test_prompts:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Novo prompt de teste",
                "form_title": "Novo prompt de teste",
                "form_subtitle": "Prompt experimental local. Nao altera o prompt oficial.",
                "active_menu": "prompts_teste",
                "submit_label": "Salvar prompt de teste",
                "is_editing": False,
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
            }
        )
        return context


class TestPromptUpdateView(LoginRequiredMixin, FormView):
    template_name = "test_prompts/form.html"
    form_class = TestPromptForm
    test_prompt: TestPrompt

    def dispatch(self, request, *args, **kwargs):
        self.test_prompt = get_object_or_404(TestPrompt, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {
            "name": self.test_prompt.name,
            "automation": str(self.test_prompt.automation_id),
            "prompt_text": self.test_prompt.prompt_text,
            "notes": self.test_prompt.notes,
            "is_active": self.test_prompt.is_active,
        }

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        automations, integration_source, integration_warnings = _load_automation_runtime_payload()
        self.integration_source = integration_source
        self.integration_warnings = integration_warnings
        choices = [
            (item.automation_id, f"{item.automation_name} ({item.automation_id})")
            for item in automations
        ]
        if str(self.test_prompt.automation_id) not in {str(choice_id) for choice_id, _ in choices}:
            choices.append(
                (
                    self.test_prompt.automation_id,
                    f"Automacao atual ({self.test_prompt.automation_id})",
                )
            )
        kwargs["automation_choices"] = choices
        return kwargs

    def form_valid(self, form):
        self.test_prompt.name = form.cleaned_data["name"]
        self.test_prompt.automation_id = form.cleaned_data["automation"]
        self.test_prompt.prompt_text = form.cleaned_data["prompt_text"]
        self.test_prompt.notes = form.cleaned_data.get("notes") or ""
        self.test_prompt.is_active = bool(form.cleaned_data.get("is_active", False))
        self.test_prompt.updated_by = self.request.user if self.request.user.is_authenticated else None
        self.test_prompt.save(update_fields=["name", "automation_id", "prompt_text", "notes", "is_active", "updated_by", "updated_at"])
        messages.success(self.request, "Prompt de teste atualizado com sucesso.")
        return redirect("test_prompts:detail", pk=self.test_prompt.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Editar prompt de teste",
                "form_title": "Editar prompt de teste",
                "form_subtitle": "Prompt experimental local. Nao altera o prompt oficial.",
                "active_menu": "prompts_teste",
                "submit_label": "Salvar alteracoes",
                "is_editing": True,
                "object": self.test_prompt,
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": getattr(self, "integration_warnings", []),
            }
        )
        return context


class TestPromptDetailView(LoginRequiredMixin, TemplateView):
    template_name = "test_prompts/detail.html"
    test_prompt: TestPrompt
    automation_runtime: AutomationRuntimeReadItem | None = None
    integration_warnings: list[str]

    def dispatch(self, request, *args, **kwargs):
        self.test_prompt = get_object_or_404(TestPrompt, pk=kwargs["pk"])
        self.integration_warnings = []
        try:
            self.automation_runtime = AutomationPromptsExecutionService().get_automation_runtime(
                automation_id=self.test_prompt.automation_id
            )
            self.integration_source = "api"
        except AutomationPromptsExecutionServiceError as exc:
            self.automation_runtime = None
            self.integration_source = "unavailable"
            self.integration_warnings.append(str(exc))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": self.test_prompt.name,
                "active_menu": "prompts_teste",
                "test_prompt": self.test_prompt,
                "automation_runtime": self.automation_runtime,
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": self.integration_warnings,
            }
        )
        return context


class TestPromptExecutionCreateView(LoginRequiredMixin, FormView):
    template_name = "test_prompts/execute.html"
    form_class = TestPromptExecutionForm
    test_prompt: TestPrompt
    automation_runtime: AutomationRuntimeReadItem | None = None
    integration_warnings: list[str]

    def dispatch(self, request, *args, **kwargs):
        self.test_prompt = get_object_or_404(TestPrompt, pk=kwargs["pk"])
        self.integration_warnings = []
        try:
            self.automation_runtime = AutomationPromptsExecutionService().get_automation_runtime(
                automation_id=self.test_prompt.automation_id
            )
            self.integration_source = "api"
        except AutomationPromptsExecutionServiceError as exc:
            self.automation_runtime = None
            self.integration_source = "unavailable"
            self.integration_warnings.append(str(exc))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        service = AutomationPromptsExecutionService()
        try:
            result = service.start_execution(
                automation_id=self.test_prompt.automation_id,
                uploaded_file=form.cleaned_data["request_file"],
                prompt_override=self.test_prompt.prompt_text,
            )
        except AutomationPromptsExecutionServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(
            self.request,
            "Execucao de teste iniciada em modo override local (prompt oficial nao foi alterado).",
        )
        return redirect(
            "test_prompts:execution_detail",
            pk=self.test_prompt.pk,
            execution_id=str(result.execution_id),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": "Executar prompt de teste",
                "active_menu": "prompts_teste",
                "test_prompt": self.test_prompt,
                "automation_runtime": self.automation_runtime,
                "integration_source": getattr(self, "integration_source", "unavailable"),
                "integration_warnings": self.integration_warnings,
            }
        )
        return context


class TestPromptExecutionDetailView(LoginRequiredMixin, TemplateView):
    template_name = "test_prompts/execution_detail.html"
    test_prompt: TestPrompt
    execution_status: AutomationExecutionStatusItem | None = None
    execution_files: list[AutomationExecutionFileItem] = []
    integration_warnings: list[str]

    def dispatch(self, request, *args, **kwargs):
        self.test_prompt = get_object_or_404(TestPrompt, pk=kwargs["pk"])
        self.integration_warnings = []
        return super().dispatch(request, *args, **kwargs)

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
        if self.execution_status.automation_id != self.test_prompt.automation_id:
            self.integration_warnings.append(
                "A execucao carregada pertence a outra automacao oficial. Verifique o vinculo antes de usar o resultado."
            )
        try:
            self.execution_files = service.list_execution_files(execution_id=execution_id)
        except AutomationPromptsExecutionServiceError as exc:
            self.execution_files = []
            self.integration_source = "api_partial"
            self.integration_warnings.append(str(exc))

    def get(self, request, *args, **kwargs):
        execution_id = self._parse_execution_id()
        try:
            self._load_execution(execution_id=execution_id)
        except AutomationPromptsExecutionServiceError as exc:
            messages.error(request, f"Nao foi possivel carregar a execucao de teste: {exc}")
            return redirect("test_prompts:detail", pk=self.test_prompt.pk)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        execution = self.execution_status
        if execution is None:
            execution = AutomationExecutionStatusItem(
                execution_id=UUID("00000000-0000-0000-0000-000000000000"),
                analysis_request_id=UUID("00000000-0000-0000-0000-000000000000"),
                automation_id=self.test_prompt.automation_id,
                request_file_id=None,
                request_file_name=None,
                prompt_override_applied=False,
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
        for file_item in self.execution_files:
            file_rows.append(
                {
                    "id": file_item.id,
                    "file_type": file_item.file_type,
                    "file_name": file_item.file_name,
                    "file_size_display": _format_file_size(file_item.file_size),
                    "created_at": file_item.created_at,
                    "download_url": reverse("test_prompts:execution_file_download", kwargs={"file_id": str(file_item.id)}),
                }
            )

        context.update(
            {
                "page_title": f"Execucao de teste {execution.execution_id}",
                "active_menu": "prompts_teste",
                "test_prompt": self.test_prompt,
                "execution": execution,
                "status_label": status_meta["label"],
                "status_css_class": status_meta["css_class"],
                "is_terminal": is_terminal,
                "auto_refresh_seconds": 4 if not is_terminal else 0,
                "file_rows": file_rows,
                "integration_source": getattr(self, "integration_source", "api"),
                "integration_warnings": self.integration_warnings,
            }
        )
        return context


class TestPromptExecutionFileDownloadView(LoginRequiredMixin, View):
    def get(self, request, file_id: str):
        try:
            file_uuid = UUID(str(file_id))
        except ValueError:
            messages.error(request, "ID de arquivo invalido para download.")
            return redirect("test_prompts:list")

        payload = AutomationPromptsExecutionService().download_execution_file(file_id=file_uuid)
        if not payload.get("ok"):
            messages.error(
                request,
                str(payload.get("error") or "Falha ao baixar arquivo remoto da execucao."),
            )
            referer = str(request.META.get("HTTP_REFERER") or "").strip()
            if referer:
                return redirect(referer)
            return redirect("test_prompts:list")

        response = HttpResponse(
            payload.get("content") or b"",
            content_type=str(payload.get("content_type") or "application/octet-stream"),
        )
        filename = str(payload.get("filename") or f"{file_uuid}.bin")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        checksum = payload.get("checksum")
        if checksum:
            response["X-File-Checksum"] = str(checksum)
        return response


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
