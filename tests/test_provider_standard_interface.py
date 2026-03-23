import httpx

from app.integrations.providers.anthropic_provider import AnthropicProvider
from app.integrations.providers.base import ProviderResponse, ProviderResponseUsage, provider_response_to_execution_result
from app.integrations.providers.gemini_provider import GeminiProvider


def test_provider_response_adapter_preserves_execution_result_contract() -> None:
    response = ProviderResponse(
        content="resultado",
        raw_response={"provider_debug": {"status_code": 200}},
        usage=ProviderResponseUsage(input_tokens=10, output_tokens=4),
        metadata={"model": "x"},
    )

    execution_result = provider_response_to_execution_result(response)

    assert execution_result.output_text == "resultado"
    assert execution_result.input_tokens == 10
    assert execution_result.output_tokens == 4
    assert execution_result.raw_response["provider_debug"]["status_code"] == 200


def test_anthropic_provider_adds_standard_debug_metadata(monkeypatch) -> None:
    provider = AnthropicProvider(api_key="sk-ant-live")

    def fake_post(url, *, headers, json, timeout):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "ok anthropic"}],
                "usage": {"input_tokens": 8, "output_tokens": 3},
            },
            headers={"anthropic-request-id": "ant-req-1"},
            request=request,
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    result = provider.execute_prompt(
        prompt="teste",
        model_name="claude-3-7-sonnet-latest",
        max_tokens=512,
        temperature=0.2,
        client_request_id="ant-client-id-1",
    )

    debug = result.raw_response.get("provider_debug") or {}
    assert debug["provider_name"] == "Anthropic"
    assert debug["token_limit_param_used"] == "max_tokens"
    assert debug["client_request_id"] == "ant-client-id-1"
    assert debug["provider_request_id"] == "ant-req-1"
    assert debug["status_code"] == 200
    assert debug["retry_attempted"] is False


def test_gemini_provider_adds_standard_debug_metadata(monkeypatch) -> None:
    provider = GeminiProvider(api_key="gemini-live")

    def fake_generate_content(**kwargs):  # type: ignore[no-untyped-def]
        return {
            "candidates": [{"content": {"parts": [{"text": "ok gemini"}]}}],
            "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 2},
            "provider_debug": {
                "provider_name": "Gemini",
                "provider_slug": "gemini",
                "model": "gemini-2.5-pro",
                "request_profile_resolved": "legacy_chat",
                "token_limit_param_used": "maxOutputTokens",
                "client_request_id": "gem-client-1",
                "provider_request_id": "gem-req-1",
                "endpoint": "models/gemini-2.5-pro:generateContent",
                "status_code": 200,
                "duration_ms": 12,
                "retry_attempted": False,
                "retry_count": 0,
                "error_type": "",
            },
        }

    monkeypatch.setattr(provider.client, "generate_content", fake_generate_content)
    result = provider.execute_prompt(
        prompt="teste",
        model_name="gemini-2.5-pro",
        max_tokens=512,
        temperature=0.2,
        client_request_id="gem-client-1",
    )

    debug = result.raw_response.get("provider_debug") or {}
    assert debug["provider_name"] == "Gemini"
    assert debug["client_request_id"] == "gem-client-1"
    assert debug["status_code"] == 200
    assert debug["retry_attempted"] is False
