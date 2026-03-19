from __future__ import annotations

from typing import Any

import httpx

from app.core.exceptions import AppException
from app.services.providers.http_client_utils import (
    raise_provider_http_exception,
    resolve_timeout_seconds,
)


class OpenAIAdminClient:
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def list_models(
        self,
        *,
        api_key: str,
        config_json: dict[str, Any],
        default_timeout_seconds: int,
    ) -> list[dict[str, Any]]:
        base_url = str(config_json.get("base_url") or self.DEFAULT_BASE_URL).rstrip("/")
        timeout_seconds = resolve_timeout_seconds(
            config_json=config_json,
            default_timeout_seconds=default_timeout_seconds,
        )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        organization = str(config_json.get("organization") or "").strip()
        if organization:
            headers["OpenAI-Organization"] = organization

        try:
            response = httpx.get(
                f"{base_url}/models",
                headers=headers,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AppException(
                "Provider request timed out.",
                status_code=504,
                code="provider_timeout",
                details={"provider": "openai"},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise_provider_http_exception(provider="openai", exc=exc)
        except httpx.HTTPError as exc:
            raise AppException(
                "Failed to communicate with provider.",
                status_code=502,
                code="provider_network_error",
                details={"provider": "openai"},
            ) from exc

        payload = response.json()
        if not isinstance(payload, dict):
            raise AppException(
                "Provider response is invalid.",
                status_code=502,
                code="provider_invalid_response",
                details={"provider": "openai"},
            )

        items = payload.get("data")
        if not isinstance(items, list):
            raise AppException(
                "Provider response has no models list.",
                status_code=502,
                code="provider_invalid_response",
                details={"provider": "openai"},
            )
        return [item for item in items if isinstance(item, dict)]
