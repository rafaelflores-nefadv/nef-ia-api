from collections.abc import Callable

from app.core.exceptions import AppException
from app.integrations.providers.anthropic_provider import AnthropicProvider
from app.integrations.providers.base import AiProviderClient
from app.integrations.providers.gemini_provider import GeminiProvider
from app.integrations.providers.openai_provider import OpenAIProvider
from app.services.providers.provider_resolution import resolve_discovery_provider_slug


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[str, int], AiProviderClient]] = {
            "openai": lambda api_key, timeout: OpenAIProvider(api_key=api_key, timeout_seconds=timeout),
            "anthropic": lambda api_key, timeout: AnthropicProvider(api_key=api_key, timeout_seconds=timeout),
            "gemini": lambda api_key, timeout: GeminiProvider(api_key=api_key, timeout_seconds=timeout),
        }

    def build(self, *, provider_slug: str, api_key: str, timeout_seconds: int) -> AiProviderClient:
        canonical_provider_slug = resolve_discovery_provider_slug(provider_slug) or provider_slug
        factory = self._factories.get(canonical_provider_slug)
        if factory is None:
            raise AppException(
                "Provider is not supported yet.",
                status_code=422,
                code="provider_not_supported",
                details={
                    "provider_slug": provider_slug,
                    "canonical_provider_slug": canonical_provider_slug,
                },
            )
        return factory(api_key, timeout_seconds)
