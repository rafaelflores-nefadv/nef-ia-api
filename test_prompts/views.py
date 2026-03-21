from __future__ import annotations

import base64
import binascii
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
    AutomationPromptsExecutionService,
    AutomationPromptsExecutionServiceError,
    PromptTestExecutionResultItem,
)
from test_automations.models import TestAutomation

from .forms import TestPromptExecutionForm, TestPromptForm
from .models import TestPrompt, TestPromptExecution


def _execution_status_meta(status: str) -> dict[str, str]:
    table = {
        "completed": {"label": "Concluida", "css_class": "status-success"},
        "failed": {"label": "Falhou", "css_class": "status-danger"},
    }
    normalized = str(status or "").strip().lower()
    return table.get(normalized, {"label": normalized or "Desconhecido", "css_class": "status-neutral"})


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


def _decode_output_file(payload: PromptTestExecutionResultItem) -> bytes | None:
    raw_base64 = str(payload.output_file_base64 or "").strip()
    if not raw_base64:
        return None
    try:
        return base64.b64decode(raw_base64)
    except (ValueError, binascii.Error):
        return None


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
                "form_subtitle": "Prompt experimental local. Nao altera prompt oficial.",
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
                "form_subtitle": "Prompt experimental local. Nao altera prompt oficial.",
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
    test_automations: list[TestAutomation]

    def dispatch(self, request, *args, **kwargs):
        self.test_prompt = get_object_or_404(TestPrompt, pk=kwargs["pk"])
        self.test_automations = _load_test_automations(active_only=True)
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

    def _build_execution_record(
        self,
        *,
        automation: TestAutomation,
        uploaded_file,
        status: str,
        result_type: str,
        output_text: str = "",
        output_file_content: bytes | None = None,
        output_file_name: str = "",
        output_file_mime_type: str = "",
        output_file_checksum: str = "",
        output_file_size: int = 0,
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
            status=status,
            result_type=result_type,
            output_text=output_text,
            output_file_name=output_file_name,
            output_file_mime_type=output_file_mime_type,
            output_file_size=output_file_size,
            output_file_content=output_file_content,
            output_file_checksum=output_file_checksum,
            provider_calls=provider_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            duration_ms=duration_ms,
            error_message=error_message,
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )

    def form_valid(self, form):
        automation_id = None
        try:
            automation_id = UUID(str(form.cleaned_data.get("automation") or "").strip())
        except ValueError:
            form.add_error("automation", "Automacao invalida.")
            return self.form_invalid(form)

        automation = next((item for item in self.test_automations if item.id == automation_id), None)
        if automation is None:
            form.add_error("automation", "Automacao de teste nao encontrada ou inativa.")
            return self.form_invalid(form)

        uploaded_file = form.cleaned_data["request_file"]
        service = AutomationPromptsExecutionService()

        if self.test_prompt.automation_id != automation.id:
            self.test_prompt.automation_id = automation.id
            self.test_prompt.updated_by = self.request.user if self.request.user.is_authenticated else None
            self.test_prompt.save(update_fields=["automation_id", "updated_by", "updated_at"])

        try:
            result = service.execute_test_prompt(
                provider_id=automation.provider_id,
                model_id=automation.model_id,
                credential_id=automation.credential_id,
                uploaded_file=uploaded_file,
                prompt_override=self.test_prompt.prompt_text,
            )
        except AutomationPromptsExecutionServiceError as exc:
            execution = self._build_execution_record(
                automation=automation,
                uploaded_file=uploaded_file,
                status=TestPromptExecution.STATUS_FAILED,
                result_type=TestPromptExecution.RESULT_TEXT,
                error_message=str(exc),
            )
            messages.error(self.request, "A execucao de teste falhou. O erro foi salvo no historico local.")
            return redirect(
                "test_prompts:execution_detail",
                pk=self.test_prompt.pk,
                execution_id=str(execution.id),
            )

        output_file_content = _decode_output_file(result)
        execution = self._build_execution_record(
            automation=automation,
            uploaded_file=uploaded_file,
            status=TestPromptExecution.STATUS_COMPLETED,
            result_type=(
                TestPromptExecution.RESULT_FILE
                if result.result_type == TestPromptExecution.RESULT_FILE
                else TestPromptExecution.RESULT_TEXT
            ),
            output_text=result.output_text or "",
            output_file_content=output_file_content,
            output_file_name=result.output_file_name or "",
            output_file_mime_type=result.output_file_mime_type or "",
            output_file_checksum=result.output_file_checksum or "",
            output_file_size=result.output_file_size,
            provider_calls=result.provider_calls,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            estimated_cost=result.estimated_cost,
            duration_ms=result.duration_ms,
        )
        messages.success(self.request, "Execucao de teste concluida e registrada localmente.")
        return redirect(
            "test_prompts:execution_detail",
            pk=self.test_prompt.pk,
            execution_id=str(execution.id),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_automation = str(getattr(context.get("form"), "cleaned_data", {}).get("automation") or "").strip()
        if not selected_automation and context.get("form") is not None:
            selected_automation = str(context["form"].fields["automation"].initial or "").strip()

        selected_automation_item = None
        for item in self.test_automations:
            if str(item.id) == selected_automation:
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
                "integration_source": "local",
                "integration_warnings": [],
                "automation_management_url": reverse("test_automations:list"),
                "automation_create_url": reverse("test_automations:create"),
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
            raise Http404("ID de execucao invalido.") from exc
        self.execution = get_object_or_404(TestPromptExecution, pk=execution_uuid, test_prompt=self.test_prompt)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        status_meta = _execution_status_meta(self.execution.status)
        output_download_url = None
        if self.execution.result_type == TestPromptExecution.RESULT_FILE and self.execution.output_file_content:
            output_download_url = reverse(
                "test_prompts:execution_output_download",
                kwargs={"pk": self.test_prompt.pk, "execution_id": str(self.execution.id)},
            )
        context.update(
            {
                "page_title": f"Execucao de teste {self.execution.id}",
                "active_menu": "prompts_teste",
                "test_prompt": self.test_prompt,
                "execution": self.execution,
                "status_label": status_meta["label"],
                "status_css_class": status_meta["css_class"],
                "integration_source": "local",
                "integration_warnings": [],
                "output_download_url": output_download_url,
                "request_file_size_display": _format_file_size(int(self.execution.request_file_size or 0)),
                "output_file_size_display": _format_file_size(int(self.execution.output_file_size or 0)),
            }
        )
        return context


class TestPromptExecutionOutputDownloadView(LoginRequiredMixin, View):
    def get(self, request, pk: int, execution_id: str):
        test_prompt = get_object_or_404(TestPrompt, pk=pk)
        try:
            execution_uuid = UUID(str(execution_id))
        except ValueError:
            messages.error(request, "ID de execucao invalido para download.")
            return redirect("test_prompts:detail", pk=test_prompt.pk)

        execution = get_object_or_404(TestPromptExecution, pk=execution_uuid, test_prompt=test_prompt)
        if not execution.output_file_content:
            messages.error(request, "Esta execucao nao possui arquivo de saida salvo.")
            return redirect("test_prompts:execution_detail", pk=test_prompt.pk, execution_id=str(execution.id))

        response = HttpResponse(
            execution.output_file_content,
            content_type=execution.output_file_mime_type or "application/octet-stream",
        )
        filename = execution.output_file_name or f"{execution.id}.bin"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        if execution.output_file_checksum:
            response["X-File-Checksum"] = execution.output_file_checksum
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
