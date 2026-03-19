from app.services.providers.provider_resolution import (
    normalize_provider_slug,
    resolve_discovery_provider_slug,
)


def test_provider_resolution_supports_gemini_aliases() -> None:
    assert resolve_discovery_provider_slug("gemini") == "gemini"
    assert resolve_discovery_provider_slug("google") == "gemini"
    assert resolve_discovery_provider_slug("google-ai") == "gemini"
    assert resolve_discovery_provider_slug("google_gemini") == "gemini"
    assert resolve_discovery_provider_slug("Google Gemini") == "gemini"


def test_provider_resolution_keeps_existing_aliases() -> None:
    assert resolve_discovery_provider_slug("openai") == "openai"
    assert resolve_discovery_provider_slug("claude") == "anthropic"
    assert normalize_provider_slug("  CLAUDE  ") == "claude"
