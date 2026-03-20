from django import forms
from django.core.exceptions import ValidationError

from core.services.provider_models_api_service import ProviderModelsAPIService
from models_catalog.models import ProviderModel

from .models import AIPrompt


def _sync_local_provider_models_for_prompt_form() -> None:
    """
    Tenta atualizar o espelho local de modelos via FastAPI antes de montar o select.

    Fluxo defensivo:
    - sucesso remoto: preenche/atualiza mirror local (fonte oficial = API)
    - falha remota: preserva fluxo legado local sem quebrar formulario
    """

    try:
        ProviderModelsAPIService().get_models_list()
    except Exception:
        # Formulario de prompts permanece funcional com dados locais em caso de falha de integracao.
        return


class AIPromptForm(forms.ModelForm):
    class Meta:
        model = AIPrompt
        fields = ["title", "ai_model", "content", "is_active"]
        labels = {
            "title": "Titulo",
            "ai_model": "Modelo de IA",
            "content": "Conteudo",
            "is_active": "Ativo",
        }
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex.: Extracao de resumo executivo",
                    "maxlength": 120,
                }
            ),
            "ai_model": forms.Select(attrs={"class": "form-select"}),
            "content": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 12,
                    "placeholder": "Descreva o prompt que sera utilizado pelo fluxo administrativo.",
                }
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _sync_local_provider_models_for_prompt_form()
        self.fields["ai_model"].queryset = ProviderModel.objects.select_related("provider").order_by(
            "provider__name",
            "name",
        )

    def clean_title(self):
        title = str(self.cleaned_data.get("title") or "").strip()
        if not title:
            raise ValidationError("Titulo e obrigatorio.")
        return title

    def clean_content(self):
        content = str(self.cleaned_data.get("content") or "").strip()
        if not content:
            raise ValidationError("Conteudo e obrigatorio.")
        return content


class PromptTestForm(forms.Form):
    prompt = forms.ModelChoiceField(
        label="Prompt",
        queryset=AIPrompt.objects.none(),
        required=True,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Selecione um prompt ativo",
    )
    request_file = forms.FileField(
        label="Arquivo",
        required=True,
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["prompt"].queryset = (
            AIPrompt.objects.select_related("ai_model", "ai_model__provider")
            .filter(
                is_active=True,
                ai_model__is_active=True,
                ai_model__provider__is_active=True,
            )
            .order_by("title")
        )

    def clean_request_file(self):
        uploaded_file = self.cleaned_data.get("request_file")
        if uploaded_file is None:
            raise ValidationError("Arquivo obrigatorio.")
        if not str(getattr(uploaded_file, "name", "") or "").strip():
            raise ValidationError("Arquivo invalido para teste.")
        return uploaded_file
