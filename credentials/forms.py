import json

from django import forms
from django.core.exceptions import ValidationError

from providers.models import Provider

from .models import ProviderCredential


class ProviderCredentialForm(forms.ModelForm):
    api_key = forms.CharField(
        label="API key",
        required=True,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Informe a API key"},
            render_value=False,
        ),
    )
    config_json = forms.CharField(
        label="Configuração JSON",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 6,
                "placeholder": '{"timeout": 30, "region": "us-east-1"}',
            }
        ),
    )

    class Meta:
        model = ProviderCredential
        fields = ["provider", "name", "api_key", "config_json", "is_active"]
        labels = {
            "provider": "Provider",
            "name": "Nome",
            "is_active": "Ativo",
        }
        widgets = {
            "provider": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ex.: Chave principal"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"].queryset = Provider.objects.order_by("name")

        if self.instance and self.instance.pk:
            self.fields["api_key"].required = False
            self.initial["api_key"] = ""

            if self.instance.config_json:
                self.initial["config_json"] = json.dumps(
                    self.instance.config_json, indent=2, ensure_ascii=False
                )
            else:
                self.initial["config_json"] = ""

    def clean_api_key(self):
        api_key = (self.cleaned_data.get("api_key") or "").strip()

        if self.instance and self.instance.pk:
            if not api_key:
                return self.instance.api_key
            return api_key

        if not api_key:
            raise ValidationError("API key e obrigatoria na criacao.")

        return api_key

    def clean_config_json(self):
        raw = (self.cleaned_data.get("config_json") or "").strip()
        if not raw:
            return {}

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"JSON inválido: {exc.msg}.") from exc

        if not isinstance(parsed, dict):
            raise ValidationError(
                "A configuração deve ser um objeto JSON (chave/valor)."
            )

        return parsed
