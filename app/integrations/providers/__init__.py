"""Provider integration package."""

from app.integrations.providers.base import AiProviderClient, ProviderExecutionResult

__all__ = [
    "AiProviderClient",
    "ProviderExecutionResult",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "ProviderRegistry",
]


def __getattr__(name: str):
    if name == "ProviderRegistry":
        from app.integrations.providers.registry import ProviderRegistry

        return ProviderRegistry
    if name == "OpenAIProvider":
        from app.integrations.providers.openai_provider import OpenAIProvider

        return OpenAIProvider
    if name == "AnthropicProvider":
        from app.integrations.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider
    if name == "GeminiProvider":
        from app.integrations.providers.gemini_provider import GeminiProvider

        return GeminiProvider
    raise AttributeError(name)
