from django import forms

from .models import Provider


class ProviderForm(forms.ModelForm):
    class Meta:
        model = Provider
        fields = ["name", "slug", "description", "is_active"]
        labels = {
            "name": "Nome",
            "slug": "Slug",
            "description": "Descricao",
            "is_active": "Ativo",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex.: OpenAI",
                }
            ),
            "slug": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex.: openai",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Descricao opcional do provider.",
                }
            ),
            "is_active": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }

    def clean_slug(self):
        return self.cleaned_data["slug"].strip().lower()
