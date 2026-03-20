from uuid import UUID

from django import forms
from django.core.exceptions import ValidationError


class TestPromptForm(forms.Form):
    name = forms.CharField(
        label="Nome do prompt experimental",
        max_length=160,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ex.: Classificacao homologacao lote 1",
            }
        ),
    )
    automation = forms.ChoiceField(
        label="Automacao oficial",
        required=True,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    prompt_text = forms.CharField(
        label="Texto do prompt de teste",
        required=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 12,
                "placeholder": "Prompt experimental local (nao altera prompt oficial).",
            }
        ),
    )
    notes = forms.CharField(
        label="Observacoes",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Observacoes de homologacao/opcional.",
            }
        ),
    )
    is_active = forms.BooleanField(
        label="Ativo",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, **kwargs):
        automation_choices = kwargs.pop("automation_choices", [])
        super().__init__(*args, **kwargs)
        self.fields["automation"].choices = [("", "Selecione uma automacao")] + [
            (str(automation_id), label)
            for automation_id, label in automation_choices
        ]

    def clean_name(self) -> str:
        value = str(self.cleaned_data.get("name") or "").strip()
        if not value:
            raise ValidationError("Nome e obrigatorio.")
        return value

    def clean_automation(self) -> str:
        raw_value = str(self.cleaned_data.get("automation") or "").strip()
        if not raw_value:
            raise ValidationError("Selecione uma automacao oficial.")
        try:
            parsed = UUID(raw_value)
        except ValueError as exc:
            raise ValidationError("Automacao invalida.") from exc
        return str(parsed)

    def clean_prompt_text(self) -> str:
        value = str(self.cleaned_data.get("prompt_text") or "").strip()
        if not value:
            raise ValidationError("Texto do prompt de teste e obrigatorio.")
        return value

    def clean_notes(self) -> str:
        return str(self.cleaned_data.get("notes") or "").strip()


class TestPromptExecutionForm(forms.Form):
    request_file = forms.FileField(
        label="Arquivo de entrada",
        required=True,
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
    )

    def clean_request_file(self):
        uploaded_file = self.cleaned_data.get("request_file")
        if uploaded_file is None:
            raise ValidationError("Arquivo obrigatorio.")
        file_name = str(getattr(uploaded_file, "name", "") or "").strip()
        if not file_name:
            raise ValidationError("Arquivo invalido para execucao.")
        return uploaded_file

