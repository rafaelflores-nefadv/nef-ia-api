from django import forms

from core.models import FastAPIIntegrationConfig


class FastAPIIntegrationConfigForm(forms.ModelForm):
    class Meta:
        model = FastAPIIntegrationConfig
        fields = ["base_url", "token_name", "integration_token", "is_active"]
        labels = {
            "base_url": "URL da FastAPI",
            "token_name": "Nome do token",
            "integration_token": "Token de integracao",
            "is_active": "Integracao ativa",
        }
        widgets = {
            "base_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex.: http://127.0.0.1:8000",
                }
            ),
            "token_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex.: admin-integration",
                }
            ),
            "integration_token": forms.PasswordInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Cole o token JWT administrativo da FastAPI",
                },
                render_value=False,
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["integration_token"].required = False
        self.fields["token_name"].required = False

    def clean_base_url(self) -> str:
        value = str(self.cleaned_data.get("base_url") or "").strip()
        return value.rstrip("/")

    def clean_integration_token(self) -> str:
        token = str(self.cleaned_data.get("integration_token") or "").strip()
        if token:
            return token
        if self.instance and self.instance.pk and self.instance.integration_token:
            return self.instance.integration_token
        return ""
