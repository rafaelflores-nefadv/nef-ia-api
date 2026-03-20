from django import forms

from core.models import FastAPIIntegrationConfig


class FastAPIIntegrationConfigForm(forms.ModelForm):
    class Meta:
        model = FastAPIIntegrationConfig
        fields = ["base_url", "is_active"]
        labels = {
            "base_url": "URL da FastAPI",
            "is_active": "Integracao ativa",
        }
        widgets = {
            "base_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex.: http://127.0.0.1:8000",
                }
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_base_url(self) -> str:
        value = str(self.cleaned_data.get("base_url") or "").strip()
        return value.rstrip("/")


class FastAPIIntegrationTokenCreateForm(forms.Form):
    name = forms.CharField(
        label="Nome do token",
        min_length=3,
        max_length=120,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ex.: django-admin",
            }
        ),
    )

    def clean_name(self) -> str:
        return str(self.cleaned_data.get("name") or "").strip()


class FastAPIIntegrationTokenRegisterForm(forms.Form):
    name = forms.CharField(
        label="Nome do token existente",
        min_length=3,
        max_length=120,
        initial="django-bootstrap",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ex.: django-bootstrap",
            }
        ),
    )
    integration_token = forms.CharField(
        label="Token bootstrap (plaintext)",
        min_length=10,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ex.: ia_int_xxxxx",
            },
            render_value=False,
        ),
    )

    def clean_name(self) -> str:
        return str(self.cleaned_data.get("name") or "").strip()

    def clean_integration_token(self) -> str:
        return str(self.cleaned_data.get("integration_token") or "").strip()
