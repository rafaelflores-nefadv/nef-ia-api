from __future__ import annotations

DISCOVERY_PROVIDER_ALIAS_MAP: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "gemini": "gemini",
    "google": "gemini",
    "google-ai": "gemini",
    "google-ai-studio": "gemini",
    "google-gemini": "gemini",
    "googlegemini": "gemini",
}

SUPPORTED_DISCOVERY_PROVIDER_SLUGS = frozenset(DISCOVERY_PROVIDER_ALIAS_MAP.keys())
SUPPORTED_DISCOVERY_PROVIDER_CANONICAL_SLUGS = frozenset(DISCOVERY_PROVIDER_ALIAS_MAP.values())


def normalize_provider_slug(value: str | None) -> str:
    return str(value or "").strip().lower().replace("_", "-").replace(" ", "-")


def resolve_discovery_provider_slug(value: str | None) -> str | None:
    return DISCOVERY_PROVIDER_ALIAS_MAP.get(normalize_provider_slug(value))
