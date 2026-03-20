from django import forms


class AutomationExecutionProfileForm(forms.Form):
    execution_profile = forms.ChoiceField(
        label="Perfil operacional",
        required=True,
        choices=(
            ("standard", "standard"),
            ("heavy", "heavy"),
            ("extended", "extended"),
        ),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    is_active = forms.BooleanField(
        label="Configuracao ativa",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    max_execution_rows = forms.IntegerField(
        label="Override max_execution_rows",
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    max_provider_calls = forms.IntegerField(
        label="Override max_provider_calls",
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    max_text_chunks = forms.IntegerField(
        label="Override max_text_chunks",
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    max_tabular_row_characters = forms.IntegerField(
        label="Override max_tabular_row_characters",
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    max_execution_seconds = forms.IntegerField(
        label="Override max_execution_seconds",
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    max_context_characters = forms.IntegerField(
        label="Override max_context_characters",
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    max_context_file_characters = forms.IntegerField(
        label="Override max_context_file_characters",
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    max_prompt_characters = forms.IntegerField(
        label="Override max_prompt_characters",
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
