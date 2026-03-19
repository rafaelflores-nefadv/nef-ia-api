import pytest

from app.core.exceptions import AppException
from app.integrations.providers.anthropic_provider import AnthropicProvider
from app.integrations.providers.gemini_provider import GeminiProvider
from app.integrations.providers.openai_provider import OpenAIProvider
from app.integrations.providers.registry import ProviderRegistry


def test_provider_registry_keeps_openai_support() -> None:
    registry = ProviderRegistry()
    client = registry.build(provider_slug="openai", api_key="sk-openai", timeout_seconds=30)
    assert isinstance(client, OpenAIProvider)


def test_provider_registry_supports_claude_alias() -> None:
    registry = ProviderRegistry()
    client = registry.build(provider_slug="claude", api_key="sk-ant", timeout_seconds=30)
    assert isinstance(client, AnthropicProvider)


def test_provider_registry_supports_gemini_aliases() -> None:
    registry = ProviderRegistry()
    client = registry.build(provider_slug="google_gemini", api_key="gemini-key", timeout_seconds=30)
    assert isinstance(client, GeminiProvider)


def test_provider_registry_rejects_unknown_provider() -> None:
    registry = ProviderRegistry()
    with pytest.raises(AppException) as exc:
        registry.build(provider_slug="cohere", api_key="sk", timeout_seconds=30)
    assert exc.value.payload.code == "provider_not_supported"
