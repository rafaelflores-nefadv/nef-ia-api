from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any
from uuid import uuid4

import httpx

from app.core.exceptions import AppException
from app.integrations.providers.base import (
    ProviderExecutionResult,
    ProviderRequest,
    ProviderResponse,
    ProviderResponseUsage,
    provider_response_to_execution_result,
)
from app.services.providers.http_client_utils import (
    build_provider_transport_error_details,
    classify_provider_http_error,
    create_provider_request_trace,
    extract_response_error_info,
    finalize_provider_request_trace,
    raise_provider_http_exception,
    sanitize_provider_debug_payload,
    summarize_provider_error_message,
)


@dataclass(slots=True, frozen=True)
class OpenAIRequestProfile:
    api_family: str
    request_profile: str
    token_limit_param: str
    supports_reasoning: bool
    resolution_source: str


class OpenAIProvider:
    REQUEST_PROFILE_LEGACY_CHAT = "legacy_chat"
    REQUEST_PROFILE_GPT5_CHAT = "gpt5_chat"
    REQUEST_PROFILE_GPT5_RESPONSES = "gpt5_responses"
    API_FAMILY_CHAT_COMPLETIONS = "chat_completions"
    API_FAMILY_RESPONSES = "responses"
    TOKEN_PARAM_MAX_TOKENS = "max_tokens"
    TOKEN_PARAM_MAX_COMPLETION_TOKENS = "max_completion_tokens"
    PARAMETER_RETRYABLE_HTTP_STATUS = {400, 422}

    def __init__(self, *, api_key: str, timeout_seconds: int = 120, base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_url = base_url.rstrip("/")

    def execute_prompt(
        self,
        *,
        prompt: str,
        model_name: str,
        max_tokens: int,
        temperature: float,
        model_metadata: dict[str, Any] | None = None,
        client_request_id: str | None = None,
    ) -> ProviderExecutionResult:
        normalized_client_request_id = str(client_request_id or "").strip() or str(uuid4())
        provider_request = ProviderRequest(
            model=str(model_name or "").strip(),
            system_prompt="",
            user_prompt=str(prompt or ""),
            max_tokens=int(max_tokens),
            temperature=float(temperature),
            metadata=dict(model_metadata) if isinstance(model_metadata, dict) else {},
        )
        resolved_profile = self._resolve_request_profile(
            model_name=model_name,
            model_metadata=model_metadata,
        )
        headers = self._build_headers(client_request_id=normalized_client_request_id)
        payload = self._build_chat_payload(
            provider_request=provider_request,
            resolved_profile=resolved_profile,
        )
        request_url = f"{self.base_url}/chat/completions"
        request_trace = create_provider_request_trace(
            provider_name="OpenAI",
            provider_slug="openai",
            model_name=model_name,
            model_slug=model_name,
            resolved_model_identifier=model_name,
            request_url=request_url,
            endpoint_name="chat_completions",
            request_method="POST",
            request_timeout_seconds=self.timeout_seconds,
            request_payload=payload,
            request_headers=headers,
            extra_fields={
                "api_family_resolved": resolved_profile.api_family,
                "request_profile_resolved": resolved_profile.request_profile,
                "token_limit_param_used": resolved_profile.token_limit_param,
                "supports_reasoning": resolved_profile.supports_reasoning,
                "profile_resolution_source": resolved_profile.resolution_source,
                "client_request_id": normalized_client_request_id,
                "retry_attempted": False,
                "retry_count": 0,
                "error_type": "",
            },
        )

        retry_attempted = False
        retry_count = 0
        response: httpx.Response | None = None
        try:
            response = self._send_chat_completion(
                request_url=request_url,
                headers=headers,
                payload=payload,
            )
        except httpx.TimeoutException as exc:
            details = build_provider_transport_error_details(
                provider="openai",
                transport_exception=exc,
                request_trace=request_trace,
            )
            details["retry_attempted"] = False
            details["retry_count"] = 0
            details["error_type"] = details.get("provider_error_classification")
            raise AppException(
                summarize_provider_error_message(details=details),
                status_code=504,
                code="provider_timeout",
                details=details,
            ) from exc
        except httpx.HTTPStatusError as exc:
            if self._should_retry_parameter_error(
                response=exc.response,
                model_name=model_name,
                payload=payload,
            ):
                retry_payload = self._build_retry_payload(
                    original_payload=payload,
                    response=exc.response,
                    model_name=model_name,
                    fallback_max_tokens=max_tokens,
                )
                if retry_payload is not None:
                    retry_attempted = True
                    retry_count = 1
                    request_trace["retry_attempted"] = True
                    request_trace["retry_count"] = 1
                    request_trace["retry_reason"] = "provider_invalid_request_parameter"
                    request_trace["request_payload_sanitized"] = sanitize_provider_debug_payload(retry_payload)
                    request_trace["token_limit_param_used"] = self._resolve_token_param_from_payload(retry_payload)
                    request_trace["request_profile_resolved"] = (
                        self.REQUEST_PROFILE_GPT5_CHAT
                        if request_trace["token_limit_param_used"] == self.TOKEN_PARAM_MAX_COMPLETION_TOKENS
                        else self.REQUEST_PROFILE_LEGACY_CHAT
                    )
                    try:
                        response = self._send_chat_completion(
                            request_url=request_url,
                            headers=headers,
                            payload=retry_payload,
                        )
                        payload = retry_payload
                    except httpx.HTTPStatusError as retry_exc:
                        raise_provider_http_exception(
                            provider="openai",
                            exc=retry_exc,
                            request_trace=request_trace,
                        )
                else:
                    raise_provider_http_exception(
                        provider="openai",
                        exc=exc,
                        request_trace=request_trace,
                    )
            else:
                raise_provider_http_exception(
                    provider="openai",
                    exc=exc,
                    request_trace=request_trace,
                )
        except httpx.HTTPError as exc:
            details = build_provider_transport_error_details(
                provider="openai",
                transport_exception=exc,
                request_trace=request_trace,
            )
            details["retry_attempted"] = retry_attempted
            details["retry_count"] = retry_count
            details["error_type"] = details.get("provider_error_classification")
            raise AppException(
                summarize_provider_error_message(details=details),
                status_code=502,
                code="provider_network_error",
                details=details,
            ) from exc

        if response is None:
            raise AppException(
                "Provider returned an empty HTTP response object.",
                status_code=502,
                code="provider_invalid_response",
                details={"provider": "openai"},
            )
        provider_response = self._build_provider_response(
            provider_request=provider_request,
            response=response,
            request_trace=request_trace,
            retry_attempted=retry_attempted,
            retry_count=retry_count,
        )
        return provider_response_to_execution_result(provider_response)

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cost_input_per_1k_tokens: Decimal,
        cost_output_per_1k_tokens: Decimal,
    ) -> Decimal:
        input_cost = (Decimal(input_tokens) / Decimal(1000)) * Decimal(cost_input_per_1k_tokens)
        output_cost = (Decimal(output_tokens) / Decimal(1000)) * Decimal(cost_output_per_1k_tokens)
        return (input_cost + output_cost).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    def _build_headers(self, *, client_request_id: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Client-Request-Id": str(client_request_id or "").strip(),
        }

    def _build_chat_payload(
        self,
        *,
        provider_request: ProviderRequest,
        resolved_profile: OpenAIRequestProfile,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": provider_request.model,
            "messages": [{"role": "user", "content": provider_request.user_prompt}],
            "temperature": provider_request.temperature,
        }
        if resolved_profile.token_limit_param == self.TOKEN_PARAM_MAX_COMPLETION_TOKENS:
            payload[self.TOKEN_PARAM_MAX_COMPLETION_TOKENS] = int(provider_request.max_tokens)
        else:
            payload[self.TOKEN_PARAM_MAX_TOKENS] = int(provider_request.max_tokens)
        return payload

    def _send_chat_completion(
        self,
        *,
        request_url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        response = httpx.post(
            request_url,
            headers=headers,
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response

    def _build_provider_response(
        self,
        *,
        provider_request: ProviderRequest,
        response: httpx.Response,
        request_trace: dict[str, Any],
        retry_attempted: bool,
        retry_count: int,
    ) -> ProviderResponse:
        data = response.json()
        if not isinstance(data, dict):
            data = {"raw": data}
        output_text = self._extract_output_text(data)
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        input_tokens = int(usage.get("prompt_tokens") or self.count_tokens(provider_request.user_prompt))
        output_tokens = int(usage.get("completion_tokens") or self.count_tokens(output_text))

        provider_debug = self._build_provider_debug_metadata(
            request_trace=request_trace,
            response=response,
            retry_attempted=retry_attempted,
            retry_count=retry_count,
        )
        raw_response = dict(data)
        raw_response["provider_debug"] = provider_debug
        return ProviderResponse(
            content=output_text,
            raw_response=raw_response,
            usage=ProviderResponseUsage(
                input_tokens=max(input_tokens, 0),
                output_tokens=max(output_tokens, 0),
            ),
            metadata={
                "model": provider_request.model,
                "provider_request_id": provider_debug.get("provider_request_id"),
            },
        )

    def _build_provider_debug_metadata(
        self,
        *,
        request_trace: dict[str, Any],
        response: httpx.Response,
        retry_attempted: bool,
        retry_count: int,
    ) -> dict[str, Any]:
        finalized = finalize_provider_request_trace(request_trace)
        status_code = response.status_code
        provider_request_id = self._extract_request_id(response=response)
        debug = {
            **finalized,
            "provider_name": "OpenAI",
            "provider_slug": "openai",
            "model": str(finalized.get("model_name") or finalized.get("resolved_model_identifier") or ""),
            "request_profile_resolved": str(finalized.get("request_profile_resolved") or ""),
            "token_limit_param_used": str(finalized.get("token_limit_param_used") or ""),
            "client_request_id": str(finalized.get("client_request_id") or ""),
            "provider_request_id": provider_request_id,
            "endpoint": str(finalized.get("endpoint_name") or ""),
            "status_code": int(status_code),
            "retry_attempted": bool(retry_attempted),
            "retry_count": int(retry_count or 0),
            "error_type": "",
        }
        return debug

    def _should_retry_parameter_error(
        self,
        *,
        response: httpx.Response,
        model_name: str,
        payload: dict[str, Any],
    ) -> bool:
        if response.status_code not in self.PARAMETER_RETRYABLE_HTTP_STATUS:
            return False
        error_info = extract_response_error_info(response)
        error_code = str(error_info.get("code") or "").strip().lower()
        error_type = str(error_info.get("type") or "").strip().lower()
        error_message = str(error_info.get("message") or "").strip().lower()
        classification = classify_provider_http_error(
            details={
                "http_status_code": response.status_code,
                "provider_error_type": error_type,
                "provider_error_code": error_code,
                "provider_error_message": error_message,
                "response_body_json": self._safe_response_json(response=response),
                "response_body_text": str(response.text or ""),
            }
        )
        if classification in {"provider_auth_error", "provider_rate_limit"}:
            return False
        if classification not in {"provider_invalid_request", "provider_unsupported_parameter"}:
            return False
        normalized_model = str(model_name or "").strip().lower()
        if not normalized_model.startswith("gpt-5"):
            return False
        if self.TOKEN_PARAM_MAX_TOKENS not in payload:
            return False
        return error_code in {"unsupported_parameter", "invalid_request"} or "unsupported parameter" in error_message

    def _build_retry_payload(
        self,
        *,
        original_payload: dict[str, Any],
        response: httpx.Response,
        model_name: str,
        fallback_max_tokens: int,
    ) -> dict[str, Any] | None:
        retry_payload = dict(original_payload)
        removed_any = False
        unsupported_parameter_name = self._extract_unsupported_parameter_name(response=response)
        if unsupported_parameter_name and unsupported_parameter_name in retry_payload:
            retry_payload.pop(unsupported_parameter_name, None)
            removed_any = True

        normalized_model = str(model_name or "").strip().lower()
        if normalized_model.startswith("gpt-5") and self.TOKEN_PARAM_MAX_TOKENS in retry_payload:
            token_value = retry_payload.pop(self.TOKEN_PARAM_MAX_TOKENS)
            retry_payload[self.TOKEN_PARAM_MAX_COMPLETION_TOKENS] = token_value
            removed_any = True

        if (
            normalized_model.startswith("gpt-5")
            and self.TOKEN_PARAM_MAX_COMPLETION_TOKENS not in retry_payload
        ):
            retry_payload[self.TOKEN_PARAM_MAX_COMPLETION_TOKENS] = int(fallback_max_tokens)
            removed_any = True

        self._ensure_mutual_token_limit_params(payload=retry_payload)
        if not removed_any:
            return None
        return retry_payload

    def _ensure_mutual_token_limit_params(self, *, payload: dict[str, Any]) -> None:
        if self.TOKEN_PARAM_MAX_COMPLETION_TOKENS in payload and self.TOKEN_PARAM_MAX_TOKENS in payload:
            payload.pop(self.TOKEN_PARAM_MAX_TOKENS, None)

    def _resolve_token_param_from_payload(self, payload: dict[str, Any]) -> str:
        if self.TOKEN_PARAM_MAX_COMPLETION_TOKENS in payload:
            return self.TOKEN_PARAM_MAX_COMPLETION_TOKENS
        if self.TOKEN_PARAM_MAX_TOKENS in payload:
            return self.TOKEN_PARAM_MAX_TOKENS
        return ""

    @staticmethod
    def _extract_unsupported_parameter_name(*, response: httpx.Response) -> str:
        message = str(extract_response_error_info(response).get("message") or "")
        if not message:
            return ""
        match = re.search(r"Unsupported parameter:\s*'([^']+)'", message, flags=re.IGNORECASE)
        if match:
            return str(match.group(1) or "").strip()
        return ""

    @staticmethod
    def _safe_response_json(*, response: httpx.Response) -> Any:
        try:
            return response.json()
        except Exception:
            return None

    @staticmethod
    def _extract_request_id(*, response: httpx.Response) -> str:
        candidates = (
            "x-request-id",
            "request-id",
            "openai-request-id",
        )
        normalized_headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        for key in candidates:
            value = normalized_headers.get(key)
            if value:
                return value
        return ""

    @staticmethod
    def _extract_output_text(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AppException(
                "Provider response missing completion choices.",
                status_code=502,
                code="provider_invalid_response",
                details={"provider": "openai"},
            )

        first_choice = choices[0] if isinstance(choices[0], dict) else {}
        message = first_choice.get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict):
                    value = item.get("text")
                    if isinstance(value, str):
                        texts.append(value)
            if texts:
                return "\n".join(texts).strip()
        raise AppException(
            "Provider response has no textual content.",
            status_code=502,
            code="provider_empty_output",
            details={"provider": "openai"},
        )

    def _resolve_request_profile(
        self,
        *,
        model_name: str,
        model_metadata: dict[str, Any] | None,
    ) -> OpenAIRequestProfile:
        metadata = self._normalize_model_metadata(model_metadata=model_metadata)
        explicit_api_family = str(metadata.get("api_family") or "").strip().lower()
        explicit_token_limit_param = str(metadata.get("token_limit_param") or "").strip().lower()
        explicit_request_profile = str(metadata.get("request_profile") or "").strip().lower()
        supports_reasoning = self._coerce_bool(metadata.get("supports_reasoning"))

        if explicit_token_limit_param == self.TOKEN_PARAM_MAX_COMPLETION_TOKENS:
            return OpenAIRequestProfile(
                api_family=self.API_FAMILY_CHAT_COMPLETIONS,
                request_profile=explicit_request_profile or self.REQUEST_PROFILE_GPT5_CHAT,
                token_limit_param=self.TOKEN_PARAM_MAX_COMPLETION_TOKENS,
                supports_reasoning=bool(supports_reasoning),
                resolution_source="metadata.token_limit_param",
            )
        if explicit_token_limit_param == self.TOKEN_PARAM_MAX_TOKENS:
            return OpenAIRequestProfile(
                api_family=self.API_FAMILY_CHAT_COMPLETIONS,
                request_profile=explicit_request_profile or self.REQUEST_PROFILE_LEGACY_CHAT,
                token_limit_param=self.TOKEN_PARAM_MAX_TOKENS,
                supports_reasoning=bool(supports_reasoning),
                resolution_source="metadata.token_limit_param",
            )

        if explicit_request_profile in {
            self.REQUEST_PROFILE_GPT5_CHAT,
            self.REQUEST_PROFILE_GPT5_RESPONSES,
        }:
            return OpenAIRequestProfile(
                api_family=(
                    self.API_FAMILY_RESPONSES
                    if explicit_request_profile == self.REQUEST_PROFILE_GPT5_RESPONSES
                    else self.API_FAMILY_CHAT_COMPLETIONS
                ),
                request_profile=explicit_request_profile,
                token_limit_param=self.TOKEN_PARAM_MAX_COMPLETION_TOKENS,
                supports_reasoning=True if supports_reasoning is None else supports_reasoning,
                resolution_source="metadata.request_profile",
            )
        if explicit_request_profile == self.REQUEST_PROFILE_LEGACY_CHAT:
            return OpenAIRequestProfile(
                api_family=self.API_FAMILY_CHAT_COMPLETIONS,
                request_profile=self.REQUEST_PROFILE_LEGACY_CHAT,
                token_limit_param=self.TOKEN_PARAM_MAX_TOKENS,
                supports_reasoning=bool(supports_reasoning),
                resolution_source="metadata.request_profile",
            )

        if explicit_api_family == self.API_FAMILY_RESPONSES:
            return OpenAIRequestProfile(
                api_family=self.API_FAMILY_RESPONSES,
                request_profile=self.REQUEST_PROFILE_GPT5_RESPONSES,
                token_limit_param=self.TOKEN_PARAM_MAX_COMPLETION_TOKENS,
                supports_reasoning=True if supports_reasoning is None else supports_reasoning,
                resolution_source="metadata.api_family",
            )

        normalized_model_name = str(model_name or "").strip().lower()
        if normalized_model_name.startswith("gpt-5"):
            return OpenAIRequestProfile(
                api_family=self.API_FAMILY_CHAT_COMPLETIONS,
                request_profile=self.REQUEST_PROFILE_GPT5_CHAT,
                token_limit_param=self.TOKEN_PARAM_MAX_COMPLETION_TOKENS,
                supports_reasoning=True if supports_reasoning is None else supports_reasoning,
                resolution_source="inference.model_name",
            )

        return OpenAIRequestProfile(
            api_family=self.API_FAMILY_CHAT_COMPLETIONS,
            request_profile=self.REQUEST_PROFILE_LEGACY_CHAT,
            token_limit_param=self.TOKEN_PARAM_MAX_TOKENS,
            supports_reasoning=bool(supports_reasoning),
            resolution_source="fallback.legacy",
        )

    @staticmethod
    def _normalize_model_metadata(*, model_metadata: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(model_metadata, dict):
            return {}
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in model_metadata.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            normalized[key] = raw_value
        return normalized

    @staticmethod
    def _coerce_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
        return None
