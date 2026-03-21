from django import forms
from django.core.exceptions import ValidationError


class TestAutomationForm(forms.Form):
    name = forms.CharField(
        label="Nome da automacao de teste",
        max_length=180,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ex.: Teste OCR financeiro",
            }
        ),
    )
    provider_id = forms.ChoiceField(
        label="Provider",
        required=True,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    model_id = forms.ChoiceField(
        label="Model",
        required=True,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    is_active = forms.BooleanField(
        label="Ativa",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, **kwargs):
        provider_choices = kwargs.pop("provider_choices", [])
        model_choices = kwargs.pop("model_choices", [])
        selected_provider = kwargs.pop("selected_provider", None)
        selected_model = kwargs.pop("selected_model", None)
        super().__init__(*args, **kwargs)
        self.fields["provider_id"].choices = [("", "Selecione um provider")] + provider_choices
        self.fields["model_id"].choices = [("", "Selecione um model")] + model_choices
        if selected_provider is not None and not self.is_bound:
            self.fields["provider_id"].initial = str(selected_provider)
        if selected_model is not None and not self.is_bound:
            self.fields["model_id"].initial = str(selected_model)

    def clean_name(self) -> str:
        value = str(self.cleaned_data.get("name") or "").strip()
        if not value:
            raise ValidationError("Nome e obrigatorio.")
        return value

    def clean_provider_id(self) -> str:
        value = str(self.cleaned_data.get("provider_id") or "").strip()
        if not value:
            raise ValidationError("Provider obrigatorio.")
        return value

    def clean_model_id(self) -> str:
        value = str(self.cleaned_data.get("model_id") or "").strip()
        if not value:
            raise ValidationError("Model obrigatorio.")
        return value
