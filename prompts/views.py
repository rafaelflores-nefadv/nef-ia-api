from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView

from core.services.prompts_catalog_api_service import PromptsCatalogAPIService
from core.services.prompt_tests_service import PromptTestsService, PromptTestsServiceError

from models_catalog.models import ProviderModel

from .forms import AIPromptForm, PromptTestForm
from .models import AIPrompt


def _get_prompt_catalog_status() -> dict:
    return PromptsCatalogAPIService().diagnose_catalog()


def _build_transition_warning_message() -> str:
    return (
        "Modulo de prompts em transicao arquitetural: sem endpoint oficial de catalogo na FastAPI. "
        "Operacao aplicada apenas no legado local do Django."
    )


def _add_transition_write_warning(request, *, catalog_status: dict) -> None:
    if str(catalog_status.get("mode") or "") != "transition_local_legacy":
        return
    messages.warning(request, _build_transition_warning_message())


def _prompt_test_status_meta(status: str) -> dict[str, str]:
    table = {
        "queued": {"label": "Na fila", "css_class": "status-neutral"},
        "processing": {"label": "Processando", "css_class": "status-warning"},
        "completed": {"label": "Concluido", "css_class": "status-success"},
        "failed": {"label": "Falhou", "css_class": "status-danger"},
    }
    return table.get(status, {"label": status or "Desconhecido", "css_class": "status-neutral"})


def _parse_dt(value):
    if value is None:
        return None
    if isinstance(value, str):
        parsed = parse_datetime(value)
        if parsed is None:
            return None
        if timezone.is_aware(parsed):
            return timezone.localtime(parsed)
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    if timezone.is_aware(value):
        return timezone.localtime(value)
    return timezone.make_aware(value, timezone.get_current_timezone())


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class AIPromptListView(LoginRequiredMixin, ListView):
    model = AIPrompt
    template_name = "prompts/list.html"
    context_object_name = "prompts"

    def get_queryset(self):
        self.catalog_status = _get_prompt_catalog_status()
        queryset = (
            AIPrompt.objects.select_related("ai_model", "ai_model__provider")
            .all()
            .order_by("-updated_at", "title")
        )

        search_query = str(self.request.GET.get("q") or "").strip()
        selected_status = str(self.request.GET.get("status") or "").strip().lower()
        selected_model = str(self.request.GET.get("modelo") or "").strip()

        if search_query:
            queryset = queryset.filter(
                Q(title__icontains=search_query) | Q(content__icontains=search_query)
            )

        if selected_status == "ativo":
            queryset = queryset.filter(is_active=True)
        elif selected_status == "inativo":
            queryset = queryset.filter(is_active=False)

        if selected_model.isdigit():
            queryset = queryset.filter(ai_model_id=int(selected_model))

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        total_count = AIPrompt.objects.count()
        filtered_count = len(context.get("prompts", []))
        search_query = str(self.request.GET.get("q") or "").strip()
        selected_status = str(self.request.GET.get("status") or "").strip().lower()
        selected_model = str(self.request.GET.get("modelo") or "").strip()

        context.update(
            {
                "page_title": "Prompts",
                "page_subtitle": "Gestao administrativa de prompts da plataforma de IA.",
                "active_menu": "prompts",
                "search_query": search_query,
                "selected_status": selected_status,
                "selected_model": selected_model,
                "status_options": [
                    ("", "Todos os status"),
                    ("ativo", "Ativos"),
                    ("inativo", "Inativos"),
                ],
                "model_options": ProviderModel.objects.select_related("provider").order_by(
                    "provider__name",
                    "name",
                ),
                "filtered_count": filtered_count,
                "total_count": total_count,
                "list_counter_label": (
                    f"Exibindo {filtered_count} de {total_count} prompt(s)"
                ),
                "integration_source": str(
                    getattr(self, "catalog_status", {}).get("source") or "fallback_local"
                ),
                "integration_mode": str(
                    getattr(self, "catalog_status", {}).get("mode")
                    or "transition_local_legacy"
                ),
                "integration_warnings": list(
                    getattr(self, "catalog_status", {}).get("warnings") or []
                ),
                "catalog_endpoint_probes": list(
                    getattr(self, "catalog_status", {}).get("endpoint_probes") or []
                ),
            }
        )
        return context


class AIPromptCreateView(LoginRequiredMixin, CreateView):
    model = AIPrompt
    form_class = AIPromptForm
    template_name = "prompts/form.html"
    success_url = reverse_lazy("prompts:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        catalog_status = _get_prompt_catalog_status()
        context.update(
            {
                "page_title": "Novo prompt",
                "form_title": "Novo prompt",
                "form_subtitle": "Cadastre um prompt administrativo vinculado a um modelo de IA.",
                "active_menu": "prompts",
                "submit_label": "Salvar prompt",
                "is_editing": False,
                "integration_source": str(catalog_status.get("source") or "fallback_local"),
                "integration_mode": str(
                    catalog_status.get("mode") or "transition_local_legacy"
                ),
                "integration_warnings": list(catalog_status.get("warnings") or []),
                "catalog_endpoint_probes": list(
                    catalog_status.get("endpoint_probes") or []
                ),
            }
        )
        return context

    def form_valid(self, form):
        catalog_status = _get_prompt_catalog_status()
        response = super().form_valid(form)
        messages.success(self.request, "Prompt criado com sucesso.")
        _add_transition_write_warning(self.request, catalog_status=catalog_status)
        return response


class AIPromptUpdateView(LoginRequiredMixin, UpdateView):
    model = AIPrompt
    form_class = AIPromptForm
    template_name = "prompts/form.html"
    success_url = reverse_lazy("prompts:list")

    def get_queryset(self):
        return AIPrompt.objects.select_related("ai_model", "ai_model__provider")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        catalog_status = _get_prompt_catalog_status()
        context.update(
            {
                "page_title": "Editar prompt",
                "form_title": "Editar prompt",
                "form_subtitle": "Atualize os dados do prompt selecionado.",
                "active_menu": "prompts",
                "submit_label": "Salvar alteracoes",
                "is_editing": True,
                "integration_source": str(catalog_status.get("source") or "fallback_local"),
                "integration_mode": str(
                    catalog_status.get("mode") or "transition_local_legacy"
                ),
                "integration_warnings": list(catalog_status.get("warnings") or []),
                "catalog_endpoint_probes": list(
                    catalog_status.get("endpoint_probes") or []
                ),
            }
        )
        return context

    def form_valid(self, form):
        catalog_status = _get_prompt_catalog_status()
        response = super().form_valid(form)
        messages.success(self.request, "Prompt atualizado com sucesso.")
        _add_transition_write_warning(self.request, catalog_status=catalog_status)
        return response


@login_required
@require_POST
def ai_prompt_toggle_status(request, pk: int):
    catalog_status = _get_prompt_catalog_status()
    prompt = get_object_or_404(AIPrompt, pk=pk)
    prompt.is_active = not bool(prompt.is_active)
    prompt.save(update_fields=["is_active", "updated_at"])

    if prompt.is_active:
        messages.success(request, "Prompt ativado com sucesso.")
    else:
        messages.success(request, "Prompt desativado com sucesso.")

    _add_transition_write_warning(request, catalog_status=catalog_status)
    return redirect("prompts:list")


@login_required
@require_POST
def ai_prompt_delete(request, pk: int):
    catalog_status = _get_prompt_catalog_status()
    prompt = get_object_or_404(AIPrompt, pk=pk)
    prompt_title = str(prompt.title or "").strip() or "prompt"

    try:
        prompt.delete()
    except ProtectedError:
        messages.error(
            request,
            "Nao foi possivel excluir este prompt porque existem vinculacoes que impedem a exclusao.",
        )
        return redirect("prompts:list")
    except IntegrityError:
        messages.error(
            request,
            "Nao foi possivel excluir este prompt no momento. Verifique se ele possui vinculacoes ativas.",
        )
        return redirect("prompts:list")
    except Exception:
        messages.error(
            request,
            "Nao foi possivel excluir este prompt no momento. Tente novamente.",
        )
        return redirect("prompts:list")

    messages.success(request, f'Prompt "{prompt_title}" excluido com sucesso.')
    _add_transition_write_warning(request, catalog_status=catalog_status)
    return redirect("prompts:list")


class PromptTestCreateView(LoginRequiredMixin, FormView):
    template_name = "prompts/test_form.html"
    form_class = PromptTestForm

    def get_initial(self):
        initial = super().get_initial()
        prompt_value = str(self.request.GET.get("prompt") or "").strip()
        if prompt_value.isdigit():
            initial["prompt"] = int(prompt_value)
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        catalog_status = _get_prompt_catalog_status()
        context.update(
            {
                "page_title": "Teste de prompt",
                "form_title": "Teste de prompt",
                "form_subtitle": (
                    "Selecione um prompt ativo, anexe um arquivo e dispare a execucao real na FastAPI."
                ),
                "active_menu": "prompts",
                "submit_label": "Disparar teste",
                "integration_source": str(catalog_status.get("source") or "fallback_local"),
                "integration_mode": str(
                    catalog_status.get("mode") or "transition_local_legacy"
                ),
                "integration_warnings": list(catalog_status.get("warnings") or []),
                "catalog_endpoint_probes": list(
                    catalog_status.get("endpoint_probes") or []
                ),
            }
        )
        return context

    def form_valid(self, form):
        prompt = form.cleaned_data["prompt"]
        uploaded_file = form.cleaned_data["request_file"]

        try:
            payload = PromptTestsService().start_prompt_test(
                prompt=prompt,
                uploaded_file=uploaded_file,
            )
        except PromptTestsServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        prompt_test_id = str(payload.get("id") or "").strip()
        if not prompt_test_id:
            form.add_error(None, "FastAPI nao retornou identificador do teste de prompt.")
            return self.form_invalid(form)

        messages.success(
            self.request,
            "Teste de prompt enviado com sucesso. Acompanhe o status da execucao.",
        )
        return redirect("prompts:test_detail", test_id=prompt_test_id)


class PromptTestDetailView(LoginRequiredMixin, TemplateView):
    template_name = "prompts/test_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        test_id = self.kwargs["test_id"]
        try:
            prompt_test_uuid = UUID(str(test_id))
        except ValueError as exc:
            raise Http404("Identificador do teste de prompt invalido.") from exc

        try:
            payload = PromptTestsService().get_prompt_test_status(prompt_test_id=prompt_test_uuid)
        except PromptTestsServiceError as exc:
            raise Http404(str(exc)) from exc

        status_value = str(payload.get("status") or "").strip().lower()
        status_meta = _prompt_test_status_meta(status_value)
        is_terminal = status_value in {"completed", "failed"}

        context.update(
            {
                "page_title": "Detalhe do teste de prompt",
                "active_menu": "prompts",
                "test_id": str(payload.get("id") or test_id),
                "status_value": status_value,
                "status_label": status_meta["label"],
                "status_css_class": status_meta["css_class"],
                "prompt_title": str(payload.get("prompt_title") or "-"),
                "provider_slug": str(payload.get("provider_slug") or "-"),
                "model_slug": str(payload.get("model_slug") or "-"),
                "file_name": str(payload.get("file_name") or "-"),
                "file_size": _to_int(payload.get("file_size"), default=0),
                "created_at": _parse_dt(payload.get("created_at")),
                "started_at": _parse_dt(payload.get("started_at")),
                "finished_at": _parse_dt(payload.get("finished_at")),
                "error_message": str(payload.get("error_message") or "").strip(),
                "output_text": str(payload.get("output_text") or "").strip(),
                "is_terminal": is_terminal,
                "auto_refresh_seconds": 4 if not is_terminal else 0,
            }
        )
        return context
