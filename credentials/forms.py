import json

from django import forms
from django.core.exceptions import ValidationError

class ProviderCredentialForm(forms.Form):
    provider = forms.ChoiceField(
        label="Provider",
        required=True,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    name = forms.CharField(
        label="Nome",
        max_length=150,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Ex.: Chave principal"}
        ),
    )
    api_key = forms.CharField(
        label="API key",
        required=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Informe a API key"},
            render_value=False,
        ),
    )
    config_json = forms.CharField(
        label="Configuracao JSON",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 6,
                "placeholder": '{"timeout": 30, "region": "us-east-1"}',
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
        self.provider_choices = kwargs.pop("provider_choices", [])
        self.is_editing = bool(kwargs.pop("is_editing", False))
        self.lock_provider = bool(kwargs.pop("lock_provider", False))
        initial_config_json = kwargs.pop("initial_config_json", None)
        super().__init__(*args, **kwargs)
        self.fields["provider"].choices = [("", "Selecione um provider")] + list(
            self.provider_choices
        )
        if self.lock_provider:
            self.fields["provider"].disabled = True

        self.fields["api_key"].required = not self.is_editing

        if self.is_editing:
            self.initial["api_key"] = ""

        if initial_config_json is not None and not self.is_bound:
            if isinstance(initial_config_json, dict) and initial_config_json:
                self.initial["config_json"] = json.dumps(
                    initial_config_json,
                    indent=2,
                    ensure_ascii=False,
                )
            else:
                self.initial["config_json"] = ""

    def clean_provider(self) -> str:
        return str(self.cleaned_data.get("provider") or "").strip()

    def clean_name(self) -> str:
        return str(self.cleaned_data.get("name") or "").strip()

    def clean_api_key(self) -> str:
        api_key = (self.cleaned_data.get("api_key") or "").strip()
        if not self.is_editing and not api_key:
            raise ValidationError("API key e obrigatoria na criacao.")
        return api_key

    def clean_config_json(self) -> dict:
        raw = (self.cleaned_data.get("config_json") or "").strip()
        if not raw:
            return {}

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"JSON invalido: {exc.msg}.") from exc

        if not isinstance(parsed, dict):
            raise ValidationError(
                "A configuracao deve ser um objeto JSON (chave/valor)."
            )

        return parsed
