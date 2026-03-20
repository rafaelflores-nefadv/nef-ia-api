from __future__ import annotations

from decimal import Decimal

from django import forms


class KnownModelSelect(forms.Select):
    def __init__(self, *args, disabled_values: set[str] | None = None, **kwargs):
        self.disabled_values = disabled_values or set()
        super().__init__(*args, **kwargs)

    def create_option(
        self,
        name,
        value,
        label,
        selected,
        index,
        subindex=None,
        attrs=None,
    ):
        option = super().create_option(
            name=name,
            value=value,
            label=label,
            selected=selected,
            index=index,
            subindex=subindex,
            attrs=attrs,
        )
        option_value = str(option.get("value") or "")
        if option_value and option_value in self.disabled_values:
            option.setdefault("attrs", {})
            option["attrs"]["disabled"] = "disabled"
        return option


class ProviderModelCreateForm(forms.Form):
    provider = forms.ChoiceField(
        label="Provider",
        required=True,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    known_model = forms.ChoiceField(
        label="Modelo disponivel",
        required=True,
        widget=KnownModelSelect(attrs={"class": "form-select"}),
    )
    description = forms.CharField(
        label="Descricao",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Descricao opcional do modelo.",
            }
        ),
    )
    context_window = forms.IntegerField(
        label="Janela de contexto",
        required=False,
        min_value=1,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "Ex.: 128000", "min": 1}
        ),
    )
    input_cost_per_1k = forms.DecimalField(
        label="Custo input / 1k",
        required=False,
        decimal_places=6,
        max_digits=12,
        min_value=Decimal("0"),
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "step": "0.000001",
                "min": "0",
                "placeholder": "Ex.: 0.000400",
            }
        ),
    )
    output_cost_per_1k = forms.DecimalField(
        label="Custo output / 1k",
        required=False,
        decimal_places=6,
        max_digits=12,
        min_value=Decimal("0"),
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "step": "0.000001",
                "min": "0",
                "placeholder": "Ex.: 0.001600",
            }
        ),
    )
    is_active = forms.BooleanField(
        label="Ativo",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    catalog_help_text = (
        "Selecione um modelo disponivel do provider para evitar duplicidade e inconsistencias de catalogo."
    )
    catalog_warning = ""
    selected_known_model: dict | None = None
    available_models_source = "unavailable"
    available_models_warnings: list[str] = []
    registered_models: list[dict] = []
    selectable_models_count: int = 0

    def __init__(self, *args, **kwargs):
        self.provider_choices = kwargs.pop("provider_choices", [])
        self.catalog_provider_id = kwargs.pop("catalog_provider_id", None)
        self.catalog_model_key = kwargs.pop("catalog_model_key", None)
        self.available_models_payload = kwargs.pop("available_models_payload", None)
        super().__init__(*args, **kwargs)

        self.fields["provider"].choices = [("", "Selecione um provider")] + list(
            self.provider_choices
        )

        selected_provider_id = self._get_selected_provider_id()
        payload = self._resolve_available_models_payload(selected_provider_id=selected_provider_id)
        known_models = payload["items"]
        self.available_models_source = payload["source"]
        self.available_models_warnings = payload["warnings"]
        self.known_models_by_key = {
            str(item.get("key") or "").strip(): item for item in known_models
        }
        self.registered_models = [
            item for item in known_models if bool(item.get("is_registered"))
        ]
        self.selectable_models_count = len(
            [item for item in known_models if not bool(item.get("is_registered"))]
        )
        disabled_values = {
            str(item.get("key") or "").strip()
            for item in known_models
            if bool(item.get("is_registered"))
        }
        widget = self.fields["known_model"].widget
        if isinstance(widget, KnownModelSelect):
            widget.disabled_values = disabled_values

        if not self.is_bound and selected_provider_id:
            self.fields["provider"].initial = selected_provider_id
            model_key = str(self.catalog_model_key or "").strip()
            if model_key and model_key in self.known_models_by_key:
                self.fields["known_model"].initial = model_key

        self.fields["known_model"].choices = self._build_known_model_choices(
            selected_provider_id=selected_provider_id,
            known_models=known_models,
        )

        if not selected_provider_id:
            self.catalog_help_text = (
                "Selecione um provider para carregar os modelos disponiveis via FastAPI."
            )
        elif self.available_models_source == "provider_not_synced":
            self.catalog_warning = (
                "Provider sem vinculo remoto na FastAPI. Sincronize o provider antes de cadastrar modelos."
            )
        elif not known_models and self.available_models_source == "unavailable":
            self.catalog_warning = (
                "Nao foi possivel carregar modelos disponiveis para este provider."
            )
        elif not known_models:
            self.catalog_warning = "Nenhum modelo disponivel foi retornado para este provider."
        elif self.selectable_models_count == 0:
            self.catalog_warning = (
                "Todos os modelos retornados para este provider ja estao cadastrados."
            )
        elif self.available_models_source == "api_provider":
            self.catalog_help_text = "Modelos carregados da API do provider via FastAPI."
        elif self.available_models_source == "api_catalog":
            self.catalog_help_text = (
                "Modelos carregados da FastAPI (catalogo administrativo)."
            )
        else:
            self.catalog_help_text = "Integracao indisponivel. Revise mensagens de erro."

        selected_model_key = (
            self.data.get("known_model")
            if self.is_bound
            else self.fields["known_model"].initial
        )
        selected_model_key = str(selected_model_key or "").strip()
        self.selected_known_model = self.known_models_by_key.get(selected_model_key)

    def _resolve_available_models_payload(
        self, *, selected_provider_id: str | None
    ) -> dict[str, object]:
        if isinstance(self.available_models_payload, dict):
            raw_items = self.available_models_payload.get("items", [])
            items: list[dict] = []
            if isinstance(raw_items, list):
                for item in raw_items:
                    if not isinstance(item, dict):
                        continue
                    key = str(item.get("key") or item.get("slug") or "").strip()
                    label = str(item.get("label") or item.get("name") or key).strip()
                    name = str(item.get("name") or label or key).strip()
                    slug = str(item.get("slug") or key).strip()
                    if not key or not slug:
                        continue
                    items.append(
                        {
                            "key": key,
                            "label": label or name,
                            "name": name or slug,
                            "slug": slug,
                            "fastapi_model_id": item.get("fastapi_model_id"),
                            "provider_model_id": item.get("provider_model_id") or key,
                            "context_window": item.get("context_window"),
                            "input_cost_per_1k": item.get("input_cost_per_1k"),
                            "output_cost_per_1k": item.get("output_cost_per_1k"),
                            "description": item.get("description") or "",
                            "supports_vision": item.get("supports_vision"),
                            "supports_reasoning": item.get("supports_reasoning"),
                            "supports_thinking": item.get("supports_thinking"),
                            "raw_payload": item.get("raw_payload") if isinstance(item.get("raw_payload"), dict) else None,
                            "is_registered": bool(item.get("is_registered", False)),
                        }
                    )

            raw_warnings = self.available_models_payload.get("warnings", [])
            warnings: list[str] = []
            if isinstance(raw_warnings, list):
                warnings = [str(msg) for msg in raw_warnings if str(msg).strip()]

            return {
                "items": items,
                "source": str(self.available_models_payload.get("source", "unavailable")),
                "warnings": warnings,
            }

        if not selected_provider_id:
            return {"items": [], "source": "unavailable", "warnings": []}
        return {"items": [], "source": "unavailable", "warnings": []}

    def _get_selected_provider_id(self) -> str | None:
        provider_value = None

        if self.is_bound:
            provider_value = self.data.get("provider")
        elif self.catalog_provider_id:
            provider_value = self.catalog_provider_id
        else:
            provider_value = self.initial.get("provider")

        provider_id = str(provider_value or "").strip()
        return provider_id or None

    def _build_known_model_choices(
        self,
        *,
        selected_provider_id: str | None,
        known_models,
    ) -> list[tuple[str, str]]:
        if not selected_provider_id:
            return [("", "Selecione um provider primeiro")]
        if not known_models:
            return [("", "Nenhum modelo disponivel para este provider")]
        choices = [("", "Selecione um modelo")]
        for model in known_models:
            key = str(model.get("key") or "")
            label = str(model.get("label") or model.get("name") or key)
            if bool(model.get("is_registered")):
                label = f"{label} (ja cadastrado)"
            choices.append((key, label))
        return choices

    def clean(self):
        cleaned_data = super().clean()
        provider_remote_id = str(cleaned_data.get("provider") or "").strip()
        model_key = str(cleaned_data.get("known_model") or "").strip()

        if not provider_remote_id:
            return cleaned_data

        known_models = list(self.known_models_by_key.values())
        if not known_models:
            warning_message = str(self.catalog_warning or "").strip()
            if not warning_message and self.available_models_warnings:
                warning_message = str(self.available_models_warnings[0]).strip()
            self.add_error(
                "provider",
                warning_message or "Nao foi possivel carregar modelos disponiveis para este provider.",
            )
            return cleaned_data

        known_model = self.known_models_by_key.get(model_key)
        if known_model is None:
            self.add_error(
                "known_model",
                "Selecione um modelo disponivel valido para o provider informado.",
            )
            return cleaned_data
        if bool(known_model.get("is_registered")):
            self.add_error(
                "known_model",
                "Este modelo ja esta cadastrado para este provider.",
            )
            return cleaned_data

        self.selected_known_model = known_model
        cleaned_data["model_name"] = known_model["name"]
        cleaned_data["model_slug"] = known_model["slug"]

        if not cleaned_data.get("description"):
            cleaned_data["description"] = known_model.get("description") or ""

        if cleaned_data.get("context_window") in {None, ""}:
            cleaned_data["context_window"] = known_model.get("context_window")

        if cleaned_data.get("input_cost_per_1k") in {None, ""}:
            cleaned_data["input_cost_per_1k"] = (
                known_model.get("input_cost_per_1k") or Decimal("0")
            )

        if cleaned_data.get("output_cost_per_1k") in {None, ""}:
            cleaned_data["output_cost_per_1k"] = (
                known_model.get("output_cost_per_1k") or Decimal("0")
            )

        return cleaned_data


class ProviderModelUpdateForm(forms.Form):
    description = forms.CharField(
        label="Descricao",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Descricao opcional do modelo.",
            }
        ),
    )
    context_window = forms.IntegerField(
        label="Janela de contexto",
        required=False,
        min_value=1,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "Ex.: 128000", "min": 1}
        ),
    )
    input_cost_per_1k = forms.DecimalField(
        label="Custo input / 1k",
        required=False,
        decimal_places=6,
        max_digits=12,
        min_value=Decimal("0"),
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "step": "0.000001",
                "min": "0",
                "placeholder": "Ex.: 0.000400",
            }
        ),
    )
    output_cost_per_1k = forms.DecimalField(
        label="Custo output / 1k",
        required=False,
        decimal_places=6,
        max_digits=12,
        min_value=Decimal("0"),
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "step": "0.000001",
                "min": "0",
                "placeholder": "Ex.: 0.001600",
            }
        ),
    )
    is_active = forms.BooleanField(
        label="Ativo",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
