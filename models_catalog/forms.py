from django import forms

from providers.models import Provider

from .models import ProviderModel


class ProviderModelForm(forms.ModelForm):
    class Meta:
        model = ProviderModel
        fields = [
            "provider",
            "name",
            "slug",
            "description",
            "context_window",
            "input_cost_per_1k",
            "output_cost_per_1k",
            "is_active",
        ]
        labels = {
            "provider": "Provider",
            "name": "Nome",
            "slug": "Slug",
            "description": "Descrição",
            "context_window": "Janela de contexto",
            "input_cost_per_1k": "Custo input / 1k",
            "output_cost_per_1k": "Custo output / 1k",
            "is_active": "Ativo",
        }
        widgets = {
            "provider": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ex.: GPT-4.1"}
            ),
            "slug": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ex.: gpt-4-1"}
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Descrição opcional do modelo.",
                }
            ),
            "context_window": forms.NumberInput(
                attrs={"class": "form-control", "placeholder": "Ex.: 128000", "min": 1}
            ),
            "input_cost_per_1k": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.000001",
                    "min": "0",
                    "placeholder": "Ex.: 0.500000",
                }
            ),
            "output_cost_per_1k": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.000001",
                    "min": "0",
                    "placeholder": "Ex.: 1.000000",
                }
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"].queryset = Provider.objects.order_by("name")

    def clean_slug(self):
        return self.cleaned_data["slug"].strip().lower()
