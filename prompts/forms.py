from django import forms
from django.core.exceptions import ValidationError

from models_catalog.models import ProviderModel

from .models import AIPrompt


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
