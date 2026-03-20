from django import forms


class ProviderForm(forms.Form):
    name = forms.CharField(
        label="Nome",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ex.: OpenAI",
            }
        ),
    )
    slug = forms.CharField(
        label="Slug",
        max_length=160,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ex.: openai",
            }
        ),
    )
    description = forms.CharField(
        label="Descricao",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Descricao opcional do provider.",
            }
        ),
    )
    is_active = forms.BooleanField(
        label="Ativo",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(
            attrs={
                "class": "form-check-input",
            }
        ),
    )

    def clean_slug(self) -> str:
        return str(self.cleaned_data["slug"] or "").strip().lower()
