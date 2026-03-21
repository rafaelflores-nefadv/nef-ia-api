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
    PromptTestTechnicalRuntimeReadItem,
    TestAutomationReadItem,
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


def _load_test_runtime_payload() -> tuple[PromptTestTechnicalRuntimeReadItem | None, str, list[str]]:
    service = AutomationPromptsExecutionService()
    try:
        return service.get_test_automation_runtime(), "api", []
    except AutomationPromptsExecutionServiceError as exc:
        return None, "unavailable", [str(exc)]


def _load_test_automation_payload(*, active_only: bool = True) -> tuple[list[TestAutomationReadItem], str, list[str]]:
    service = AutomationPromptsExecutionService()
    try:
        return service.list_test_automations(active_only=active_only), "api", []
    except AutomationPromptsExecutionServiceError as exc:
        return [], "unavailable", [str(exc)]


def _build_automation_choices(automations: list[TestAutomationReadItem]) -> list[tuple[UUID, str]]:
    choices: list[tuple[UUID, str]] = []
    for item in automations:
        runtime_label = ""
        if item.provider_slug and item.model_slug:
            runtime_label = f" ({item.provider_slug} / {item.model_slug})"
        label = f"{item.automation_name}{runtime_label}"
        choices.append((item.automation_id, label))
    return choices


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
        _, runtime_source, runtime_warnings = _load_test_runtime_payload()
        test_automations, automation_source, automation_warnings = _load_test_automation_payload(active_only=True)
        prompts = context.get("test_prompts") or []
        integration_source = "api" if runtime_source == "api" and automation_source == "api" else "unavailable"
        integration_warnings = [*runtime_warnings, *automation_warnings]

        context.update(
            {
                "page_title": "Prompts de teste",
                "page_subtitle": "Uso local com runtime tecnico isolado para testes de prompt.",
                "active_menu": "prompts_teste",
                "integration_source": integration_source,
                "integration_warnings": integration_warnings,
                "test_automations_count": len(test_automations),
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

    def form_valid(self, form):
        prompt = TestPrompt(
            name=form.cleaned_data["name"],
            automation_id=None,
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
            "prompt_text": self.test_prompt.prompt_text,
            "notes": self.test_prompt.notes,
            "is_active": self.test_prompt.is_active,
        }

    def form_valid(self, form):
        self.test_prompt.name = form.cleaned_data["name"]
        self.test_prompt.prompt_text = form.cleaned_data["prompt_text"]
        self.test_prompt.notes = form.cleaned_data.get("notes") or ""
        self.test_prompt.is_active = bool(form.cleaned_data.get("is_active", False))
        self.test_prompt.updated_by = self.request.user if self.request.user.is_authenticated else None
        self.test_prompt.save(update_fields=["name", "prompt_text", "notes", "is_active", "updated_by", "updated_at"])
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
            }
        )
        return context


class TestPromptDetailView(LoginRequiredMixin, TemplateView):
    template_name = "test_prompts/detail.html"
    test_prompt: TestPrompt
    selected_automation: TestAutomationReadItem | None = None
    integration_warnings: list[str]
    integration_source: str

    def dispatch(self, request, *args, **kwargs):
        self.test_prompt = get_object_or_404(TestPrompt, pk=kwargs["pk"])
        self.selected_automation = None
        self.integration_warnings = []
        self.integration_source = "api"

        _, runtime_source, runtime_warnings = _load_test_runtime_payload()
        self.integration_warnings.extend(runtime_warnings)
        if runtime_source != "api":
            self.integration_source = runtime_source

        automations, automation_source, automation_warnings = _load_test_automation_payload(active_only=False)
        self.integration_warnings.extend(automation_warnings)
        if automation_source != "api":
            self.integration_source = automation_source

        if self.test_prompt.automation_id is not None:
            for automation in automations:
                if automation.automation_id == self.test_prompt.automation_id:
                    self.selected_automation = automation
                    break
            if self.selected_automation is None:
                self.integration_warnings.append(
                    "Automacao de teste salva no prompt nao foi encontrada na FastAPI."
                )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": self.test_prompt.name,
                "active_menu": "prompts_teste",
                "test_prompt": self.test_prompt,
                "selected_automation": self.selected_automation,
                "integration_source": self.integration_source,
                "integration_warnings": self.integration_warnings,
            }
        )
        return context


class TestPromptExecutionCreateView(LoginRequiredMixin, FormView):
    template_name = "test_prompts/execute.html"
    form_class = TestPromptExecutionForm
    test_prompt: TestPrompt
    test_automations: list[TestAutomationReadItem]
    integration_warnings: list[str]
    integration_source: str
    technical_runtime: PromptTestTechnicalRuntimeReadItem | None = None

    def dispatch(self, request, *args, **kwargs):
        self.test_prompt = get_object_or_404(TestPrompt, pk=kwargs["pk"])
        self.technical_runtime, runtime_source, runtime_warnings = _load_test_runtime_payload()
        self.test_automations, automations_source, automation_warnings = _load_test_automation_payload(active_only=True)
        self.integration_source = "api" if runtime_source == "api" and automations_source == "api" else "unavailable"
        self.integration_warnings = [*runtime_warnings, *automation_warnings]
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        choices = _build_automation_choices(self.test_automations)
        selected_automation = str(self.request.GET.get("automation") or "").strip()
        if self.request.method.upper() == "POST":
            selected_automation = str(self.request.POST.get("automation") or selected_automation).strip()
        if not selected_automation and self.test_prompt.automation_id is not None:
            selected_automation = str(self.test_prompt.automation_id)

        valid_ids = {str(automation_id) for automation_id, _ in choices}
        if selected_automation and selected_automation not in valid_ids:
            selected_automation = ""
        if not selected_automation and choices:
            selected_automation = str(choices[0][0])

        kwargs["automation_choices"] = choices
        kwargs["selected_automation"] = selected_automation or None
        return kwargs

    def form_valid(self, form):
        automation_value = str(form.cleaned_data.get("automation") or "").strip()
        if not automation_value and self.test_automations:
            automation_value = str(self.test_automations[0].automation_id)
        try:
            automation_id = UUID(automation_value)
        except ValueError:
            form.add_error("automation", "Automacao invalida.")
            return self.form_invalid(form)

        service = AutomationPromptsExecutionService()
        try:
            result = service.start_execution(
                automation_id=automation_id,
                uploaded_file=form.cleaned_data["request_file"],
                prompt_override=self.test_prompt.prompt_text,
            )
        except AutomationPromptsExecutionServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        if self.test_prompt.automation_id != automation_id:
            self.test_prompt.automation_id = automation_id
            self.test_prompt.updated_by = self.request.user if self.request.user.is_authenticated else None
            self.test_prompt.save(update_fields=["automation_id", "updated_by", "updated_at"])

        messages.success(
            self.request,
            "Execucao de teste iniciada com prompt_override e automacao de teste selecionada.",
        )
        return redirect(
            "test_prompts:execution_detail",
            pk=self.test_prompt.pk,
            execution_id=str(result.execution_id),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_automation = str(getattr(context.get("form"), "cleaned_data", {}).get("automation") or "").strip()
        if not selected_automation and context.get("form") is not None:
            selected_automation = str(context["form"].fields["automation"].initial or "").strip()

        selected_automation_item = None
        for item in self.test_automations:
            if str(item.automation_id) == selected_automation:
                selected_automation_item = item
                break
        if selected_automation_item is None and self.test_automations:
            selected_automation_item = self.test_automations[0]

        context.update(
            {
                "page_title": "Executar prompt de teste",
                "active_menu": "prompts_teste",
                "test_prompt": self.test_prompt,
                "test_automations": self.test_automations,
                "selected_automation": selected_automation_item,
                "technical_runtime": self.technical_runtime,
                "integration_source": self.integration_source,
                "integration_warnings": self.integration_warnings,
                "automation_management_url": reverse("test_automations:list"),
                "automation_create_url": reverse("test_automations:create"),
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
                automation_id=UUID("00000000-0000-0000-0000-000000000000"),
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
