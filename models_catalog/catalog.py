from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.utils.text import slugify


@dataclass(frozen=True)
class KnownModel:
    key: str
    label: str
    name: str
    slug: str
    context_window: int | None = None
    input_cost_per_1k: Decimal | None = None
    output_cost_per_1k: Decimal | None = None
    description: str = ""


KNOWN_MODELS_BY_PROVIDER: dict[str, list[KnownModel]] = {
    "openai": [
        KnownModel(
            key="gpt-4-1",
            label="GPT-4.1",
            name="GPT-4.1",
            slug="gpt-4-1",
            context_window=128000,
            input_cost_per_1k=Decimal("0.002000"),
            output_cost_per_1k=Decimal("0.008000"),
            description="Modelo multimodal com foco em qualidade e instrucoes complexas.",
        ),
        KnownModel(
            key="gpt-4-1-mini",
            label="GPT-4.1 Mini",
            name="GPT-4.1 Mini",
            slug="gpt-4-1-mini",
            context_window=128000,
            input_cost_per_1k=Decimal("0.000400"),
            output_cost_per_1k=Decimal("0.001600"),
            description="Versao otimizada para menor custo e boa performance geral.",
        ),
        KnownModel(
            key="gpt-4o",
            label="GPT-4o",
            name="GPT-4o",
            slug="gpt-4o",
            context_window=128000,
            input_cost_per_1k=Decimal("0.005000"),
            output_cost_per_1k=Decimal("0.015000"),
            description="Modelo multimodal de alta capacidade para fluxos robustos.",
        ),
        KnownModel(
            key="gpt-4o-mini",
            label="GPT-4o Mini",
            name="GPT-4o Mini",
            slug="gpt-4o-mini",
            context_window=128000,
            input_cost_per_1k=Decimal("0.000150"),
            output_cost_per_1k=Decimal("0.000600"),
            description="Modelo economico para alto volume com baixa latencia.",
        ),
    ],
    "anthropic": [
        KnownModel(
            key="claude-3-5-sonnet",
            label="Claude 3.5 Sonnet",
            name="Claude 3.5 Sonnet",
            slug="claude-3-5-sonnet",
            context_window=200000,
            input_cost_per_1k=Decimal("0.003000"),
            output_cost_per_1k=Decimal("0.015000"),
            description="Modelo equilibrado para analise e geracao de alto nivel.",
        ),
    ],
    "gemini": [
        KnownModel(
            key="gemini-1-5-pro",
            label="Gemini 1.5 Pro",
            name="Gemini 1.5 Pro",
            slug="gemini-1-5-pro",
            context_window=200000,
            input_cost_per_1k=Decimal("0.003500"),
            output_cost_per_1k=Decimal("0.010500"),
            description="Modelo com forte desempenho em contexto longo.",
        ),
    ],
    "azure-openai": [
        KnownModel(
            key="gpt-4o-mini",
            label="GPT-4o Mini (Azure)",
            name="GPT-4o Mini",
            slug="gpt-4o-mini",
            context_window=128000,
            input_cost_per_1k=Decimal("0.000150"),
            output_cost_per_1k=Decimal("0.000600"),
            description="Modelo OpenAI provisionado no Azure OpenAI.",
        ),
    ],
}


PROVIDER_ALIASES: dict[str, str] = {
    "gemini": "gemini",
    "google": "gemini",
    "google-ai": "gemini",
    "google-gemini": "gemini",
    "azure": "azure-openai",
    "azure-openai": "azure-openai",
    "azure-open-ai": "azure-openai",
    "azure_openai": "azure-openai",
}


def normalize_provider_key(value: str | None) -> str:
    if not value:
        return ""
    normalized = slugify(value).replace("_", "-")
    return PROVIDER_ALIASES.get(normalized, normalized)


def get_known_models(provider_slug: str | None) -> list[KnownModel]:
    key = normalize_provider_key(provider_slug)
    return KNOWN_MODELS_BY_PROVIDER.get(key, [])


def get_known_model(provider_slug: str | None, model_key: str | None) -> KnownModel | None:
    if not model_key:
        return None
    for model in get_known_models(provider_slug):
        if model.key == model_key:
            return model
    return None
