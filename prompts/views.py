from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from models_catalog.models import ProviderModel

from .forms import AIPromptForm
from .models import AIPrompt


class AIPromptListView(LoginRequiredMixin, ListView):
    model = AIPrompt
    template_name = "prompts/list.html"
    context_object_name = "prompts"

    def get_queryset(self):
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
        context.update(
            {
                "page_title": "Novo prompt",
                "form_title": "Novo prompt",
                "form_subtitle": "Cadastre um prompt administrativo vinculado a um modelo de IA.",
                "active_menu": "prompts",
                "submit_label": "Salvar prompt",
                "is_editing": False,
            }
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Prompt criado com sucesso.")
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
        context.update(
            {
                "page_title": "Editar prompt",
                "form_title": "Editar prompt",
                "form_subtitle": "Atualize os dados do prompt selecionado.",
                "active_menu": "prompts",
                "submit_label": "Salvar alteracoes",
                "is_editing": True,
            }
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Prompt atualizado com sucesso.")
        return response


@login_required
@require_POST
def ai_prompt_toggle_status(request, pk: int):
    prompt = get_object_or_404(AIPrompt, pk=pk)
    prompt.is_active = not bool(prompt.is_active)
    prompt.save(update_fields=["is_active", "updated_at"])

    if prompt.is_active:
        messages.success(request, "Prompt ativado com sucesso.")
    else:
        messages.success(request, "Prompt desativado com sucesso.")

    return redirect("prompts:list")


@login_required
@require_POST
def ai_prompt_delete(request, pk: int):
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
    return redirect("prompts:list")
