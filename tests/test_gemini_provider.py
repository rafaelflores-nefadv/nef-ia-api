from decimal import Decimal

import pytest

from app.core.exceptions import AppException
from app.integrations.providers.gemini_provider import GeminiProvider


def test_gemini_provider_executes_prompt_with_native_payload(monkeypatch) -> None:
    provider = GeminiProvider(api_key="gemini-live-key", timeout_seconds=45)

    def fake_generate_content(**kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["model_name"] == "gemini-2.5-pro"
        assert kwargs["prompt"] == "Resumo do arquivo"
        assert kwargs["max_output_tokens"] == 512
        assert kwargs["temperature"] == 0.1
        return {
            "candidates": [
                {"content": {"parts": [{"text": "Resumo pronto"}]}},
            ],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 11},
        }

    monkeypatch.setattr(provider.client, "generate_content", fake_generate_content)
    result = provider.execute_prompt(
        prompt="Resumo do arquivo",
        model_name="gemini-2.5-pro",
        max_tokens=512,
        temperature=0.1,
    )
    assert result.output_text == "Resumo pronto"
    assert result.input_tokens == 20
    assert result.output_tokens == 11
    assert isinstance(result.raw_response, dict)


def test_gemini_provider_raises_when_output_missing(monkeypatch) -> None:
    provider = GeminiProvider(api_key="gemini-live-key", timeout_seconds=45)

    monkeypatch.setattr(
        provider.client,
        "generate_content",
        lambda **kwargs: {"candidates": []},  # type: ignore[arg-type]
    )
    with pytest.raises(AppException) as exc:
        provider.execute_prompt(
            prompt="Teste",
            model_name="gemini-2.5-flash",
            max_tokens=256,
            temperature=0.2,
        )
    assert exc.value.payload.code == "provider_empty_output"


def test_gemini_provider_estimate_cost() -> None:
    provider = GeminiProvider(api_key="gemini-live-key", timeout_seconds=45)
    value = provider.estimate_cost(
        input_tokens=1000,
        output_tokens=500,
        cost_input_per_1k_tokens=Decimal("0.002"),
        cost_output_per_1k_tokens=Decimal("0.008"),
    )
    assert value == Decimal("0.006000")
