from django import forms
from django.core.exceptions import ValidationError


class AutomationExecutionForm(forms.Form):
    automation = forms.ChoiceField(
        label="Automacao",
        required=True,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    request_file = forms.FileField(
        label="Arquivo de entrada",
        required=True,
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        automation_choices = kwargs.pop("automation_choices", [])
        selected_automation = kwargs.pop("selected_automation", None)
        super().__init__(*args, **kwargs)

        self.fields["automation"].choices = [("", "Selecione uma automacao")] + [
            (str(automation_id), label)
            for automation_id, label in automation_choices
        ]

        if selected_automation is not None and not self.is_bound:
            self.fields["automation"].initial = str(selected_automation)

    def clean_automation(self):
        value = str(self.cleaned_data.get("automation") or "").strip()
        if not value:
            raise ValidationError("Selecione uma automacao.")
        return value

    def clean_request_file(self):
        uploaded_file = self.cleaned_data.get("request_file")
        if uploaded_file is None:
            raise ValidationError("Arquivo obrigatorio.")
        file_name = str(getattr(uploaded_file, "name", "") or "").strip()
        if not file_name:
            raise ValidationError("Arquivo invalido para execucao.")
        return uploaded_file
