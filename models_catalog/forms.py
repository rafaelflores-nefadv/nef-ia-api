from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from django import forms

from providers.models import Provider

from .models import ProviderModel


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


class ProviderModelCreateForm(forms.ModelForm):
    known_model = forms.ChoiceField(
        label="Modelo disponivel",
        required=True,
        widget=KnownModelSelect(attrs={"class": "form-select"}),
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

    class Meta:
        model = ProviderModel
        fields = [
            "provider",
            "known_model",
            "description",
            "context_window",
            "input_cost_per_1k",
            "output_cost_per_1k",
            "is_active",
        ]
        labels = {
            "provider": "Provider",
            "description": "Descricao",
            "context_window": "Janela de contexto",
            "input_cost_per_1k": "Custo input / 1k",
            "output_cost_per_1k": "Custo output / 1k",
            "is_active": "Ativo",
        }
        widgets = {
            "provider": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Descricao opcional do modelo.",
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
                    "placeholder": "Ex.: 0.000400",
                }
            ),
            "output_cost_per_1k": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.000001",
                    "min": "0",
                    "placeholder": "Ex.: 0.001600",
                }
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        self.catalog_provider_id = kwargs.pop("catalog_provider_id", None)
        self.catalog_model_key = kwargs.pop("catalog_model_key", None)
        self.available_models_payload = kwargs.pop("available_models_payload", None)
        super().__init__(*args, **kwargs)

        self.fields["provider"].queryset = Provider.objects.order_by("name")
        self.fields["context_window"].required = False
        self.fields["input_cost_per_1k"].required = False
        self.fields["output_cost_per_1k"].required = False

        selected_provider = self._get_selected_provider()
        payload = self._resolve_available_models_payload(selected_provider=selected_provider)
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

        if not self.is_bound and selected_provider is not None:
            self.fields["provider"].initial = selected_provider.pk
            model_key = str(self.catalog_model_key or "").strip()
            if model_key and model_key in self.known_models_by_key:
                self.fields["known_model"].initial = model_key

        self.fields["known_model"].choices = self._build_known_model_choices(
            selected_provider=selected_provider,
            known_models=known_models,
        )

        if selected_provider is None:
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
        elif self.available_models_source == "fallback_local":
            self.catalog_help_text = "Fallback local ativado por falha real de integracao."
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
        self, *, selected_provider: Provider | None
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

        if selected_provider is None:
            return {"items": [], "source": "unavailable", "warnings": []}
        if selected_provider.fastapi_provider_id is None:
            return {
                "items": [],
                "source": "provider_not_synced",
                "warnings": [
                    "Provider nao sincronizado com a FastAPI. Edite/salve o provider para criar o vinculo remoto."
                ],
            }
        return {"items": [], "source": "unavailable", "warnings": []}

    def _get_selected_provider(self) -> Provider | None:
        provider_value = None

        if self.is_bound:
            provider_value = self.data.get("provider")
        elif self.catalog_provider_id:
            provider_value = self.catalog_provider_id
        else:
            initial_provider = self.initial.get("provider")
            if isinstance(initial_provider, Provider):
                return initial_provider
            provider_value = initial_provider

        if not provider_value:
            return None

        try:
            return Provider.objects.get(pk=int(provider_value))
        except (TypeError, ValueError, Provider.DoesNotExist):
            return None

    def _build_known_model_choices(
        self,
        *,
        selected_provider: Provider | None,
        known_models,
    ) -> list[tuple[str, str]]:
        if selected_provider is None:
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
        provider = cleaned_data.get("provider")
        model_key = (cleaned_data.get("known_model") or "").strip()

        if provider is None:
            return cleaned_data

        known_models = list(self.known_models_by_key.values())
        if self.available_models_source == "provider_not_synced":
            self.add_error(
                "provider",
                "Provider nao sincronizado com a FastAPI. Salve o provider para gerar vinculo remoto.",
            )
            return cleaned_data
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

        if ProviderModel.objects.filter(provider=provider, slug=known_model["slug"]).exists():
            self.add_error(
                "known_model",
                "Este modelo ja esta cadastrado para este provider.",
            )
            return cleaned_data

        self.selected_known_model = known_model
        cleaned_data["name"] = known_model["name"]
        cleaned_data["slug"] = known_model["slug"]

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

    def save(self, commit=True):
        instance = super().save(commit=False)
        known_model = self.selected_known_model
        if known_model is not None:
            instance.name = known_model["name"]
            instance.slug = known_model["slug"]
            fastapi_model_id = str(known_model.get("fastapi_model_id") or "").strip()
            if fastapi_model_id:
                try:
                    instance.fastapi_model_id = UUID(fastapi_model_id)
                except ValueError:
                    instance.fastapi_model_id = None
        else:
            instance.name = self.cleaned_data["name"]
            instance.slug = self.cleaned_data["slug"]

        if commit:
            instance.save()
        return instance


class ProviderModelUpdateForm(forms.ModelForm):
    class Meta:
        model = ProviderModel
        fields = [
            "description",
            "context_window",
            "input_cost_per_1k",
            "output_cost_per_1k",
            "is_active",
        ]
        labels = {
            "description": "Descricao",
            "context_window": "Janela de contexto",
            "input_cost_per_1k": "Custo input / 1k",
            "output_cost_per_1k": "Custo output / 1k",
            "is_active": "Ativo",
        }
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Descricao opcional do modelo.",
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
                    "placeholder": "Ex.: 0.000400",
                }
            ),
            "output_cost_per_1k": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.000001",
                    "min": "0",
                    "placeholder": "Ex.: 0.001600",
                }
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
