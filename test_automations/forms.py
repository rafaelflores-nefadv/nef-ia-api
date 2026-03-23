import json

from django import forms
from django.core.exceptions import ValidationError

from .output_contract import (
    OUTPUT_TYPE_CHOICES_PT,
    RESULT_FORMATTER_CHOICES_PT,
    RESULT_PARSER_CHOICES_PT,
    validate_contract_combination,
)


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
    credential_id = forms.ChoiceField(
        label="Credencial",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    output_type = forms.ChoiceField(
        label="Tipo de saida",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    result_parser = forms.ChoiceField(
        label="Parser de resultado",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    result_formatter = forms.ChoiceField(
        label="Formatador de resultado",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    output_schema = forms.CharField(
        label="Schema de saida (JSON)",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 9,
                "placeholder": (
                    '{\n'
                    '  "columns": ["numero_processo", "descricao", "categoria"],\n'
                    '  "ai_output_columns": ["categoria"],\n'
                    '  "input_column_mappings": {"numero_processo": ["Numero Processo", "Número Processo"]},\n'
                    '  "structured_output_aliases": {"categoria": ["categoria"]},\n'
                    '  "include_input_columns": false,\n'
                    '  "file_name_template": "execution_{execution_id}_resultado.xlsx"\n'
                    "}"
                ),
            }
        ),
    )
    debug_enabled = forms.BooleanField(
        label="Modo debug da automa\u00e7\u00e3o",
        required=False,
        initial=False,
        help_text=(
            "Quando ativado, a automa\u00e7\u00e3o gera tamb\u00e9m um arquivo t\u00e9cnico de diagn\u00f3stico da execu\u00e7\u00e3o, "
            "\u00fatil para analisar a montagem do prompt, os dados utilizados, a resposta do modelo e o resultado final."
        ),
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
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
        credential_choices = kwargs.pop("credential_choices", [])
        selected_provider = kwargs.pop("selected_provider", None)
        selected_model = kwargs.pop("selected_model", None)
        selected_credential = kwargs.pop("selected_credential", None)
        selected_output_type = kwargs.pop("selected_output_type", None)
        selected_result_parser = kwargs.pop("selected_result_parser", None)
        selected_result_formatter = kwargs.pop("selected_result_formatter", None)
        initial_output_schema = kwargs.pop("initial_output_schema", None)
        super().__init__(*args, **kwargs)
        self.fields["provider_id"].choices = [("", "Selecione um provider")] + provider_choices
        self.fields["model_id"].choices = [("", "Selecione um model")] + model_choices
        self.fields["credential_id"].choices = [("", "Usar credencial ativa do provider")] + credential_choices
        self.fields["output_type"].choices = [("", "Usar padrao legado (automatico)")] + list(OUTPUT_TYPE_CHOICES_PT)
        self.fields["result_parser"].choices = [("", "Usar padrao legado (automatico)")] + list(RESULT_PARSER_CHOICES_PT)
        self.fields["result_formatter"].choices = [("", "Usar padrao legado (automatico)")] + list(
            RESULT_FORMATTER_CHOICES_PT
        )

        known_output_values = {value for value, _ in self.fields["output_type"].choices if value}
        if selected_output_type and str(selected_output_type) not in known_output_values:
            self.fields["output_type"].choices.append(
                (str(selected_output_type), f"{selected_output_type} (valor tecnico atual)")
            )
        known_parser_values = {value for value, _ in self.fields["result_parser"].choices if value}
        if selected_result_parser and str(selected_result_parser) not in known_parser_values:
            self.fields["result_parser"].choices.append(
                (str(selected_result_parser), f"{selected_result_parser} (valor tecnico atual)")
            )
        known_formatter_values = {value for value, _ in self.fields["result_formatter"].choices if value}
        if selected_result_formatter and str(selected_result_formatter) not in known_formatter_values:
            self.fields["result_formatter"].choices.append(
                (str(selected_result_formatter), f"{selected_result_formatter} (valor tecnico atual)")
            )
        if selected_provider is not None and not self.is_bound:
            self.fields["provider_id"].initial = str(selected_provider)
        if selected_model is not None and not self.is_bound:
            self.fields["model_id"].initial = str(selected_model)
        if selected_credential is not None and not self.is_bound:
            self.fields["credential_id"].initial = str(selected_credential)
        if selected_output_type is not None and not self.is_bound:
            self.fields["output_type"].initial = str(selected_output_type)
        if selected_result_parser is not None and not self.is_bound:
            self.fields["result_parser"].initial = str(selected_result_parser)
        if selected_result_formatter is not None and not self.is_bound:
            self.fields["result_formatter"].initial = str(selected_result_formatter)
        if initial_output_schema is not None and not self.is_bound:
            self.fields["output_schema"].initial = str(initial_output_schema)

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

    def clean_credential_id(self) -> str:
        return str(self.cleaned_data.get("credential_id") or "").strip()

    def clean_output_type(self) -> str:
        return str(self.cleaned_data.get("output_type") or "").strip()

    def clean_result_parser(self) -> str:
        return str(self.cleaned_data.get("result_parser") or "").strip()

    def clean_result_formatter(self) -> str:
        return str(self.cleaned_data.get("result_formatter") or "").strip()

    def clean_output_schema(self) -> str:
        return str(self.cleaned_data.get("output_schema") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        output_type = str(cleaned_data.get("output_type") or "").strip()
        result_parser = str(cleaned_data.get("result_parser") or "").strip()
        result_formatter = str(cleaned_data.get("result_formatter") or "").strip()
        output_schema_raw = str(cleaned_data.get("output_schema") or "").strip()

        output_schema_parsed = None
        if output_schema_raw:
            try:
                output_schema_parsed = json.loads(output_schema_raw)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    {"output_schema": f"Schema de saida invalido: JSON malformado ({exc.msg})."}
                ) from exc
            if not isinstance(output_schema_parsed, dict):
                raise ValidationError(
                    {"output_schema": "Schema de saida invalido: informe um objeto JSON (chave/valor)."}
                )

        compatibility_error = validate_contract_combination(
            output_type=output_type or None,
            result_parser=result_parser or None,
            result_formatter=result_formatter or None,
            has_schema=output_schema_parsed is not None,
        )
        if compatibility_error:
            raise ValidationError(compatibility_error)

        cleaned_data["output_schema_parsed"] = output_schema_parsed
        return cleaned_data


class TestAutomationCopyToOfficialForm(forms.Form):
    owner_token_id = forms.ChoiceField(
        label="Token oficial de destino",
        required=True,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        owner_token_choices = kwargs.pop("owner_token_choices", [])
        super().__init__(*args, **kwargs)
        self.fields["owner_token_id"].choices = [("", "Selecione um token oficial")] + owner_token_choices

    def clean_owner_token_id(self) -> str:
        value = str(self.cleaned_data.get("owner_token_id") or "").strip()
        if not value:
            raise ValidationError("Token oficial de destino e obrigatorio.")
        return value
