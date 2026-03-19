from __future__ import annotations

from typing import Any

import httpx

from app.core.exceptions import AppException
from app.services.providers.http_client_utils import (
    raise_provider_http_exception,
    resolve_timeout_seconds,
)


class AnthropicAdminClient:
    DEFAULT_BASE_URL = "https://api.anthropic.com"

    def list_models(
        self,
        *,
        api_key: str,
        config_json: dict[str, Any],
        anthropic_version: str,
        default_timeout_seconds: int,
    ) -> list[dict[str, Any]]:
        base_url = str(config_json.get("base_url") or self.DEFAULT_BASE_URL).rstrip("/")
        timeout_seconds = resolve_timeout_seconds(
            config_json=config_json,
            default_timeout_seconds=default_timeout_seconds,
        )
        version = str(config_json.get("anthropic_version") or anthropic_version).strip() or anthropic_version
        headers = {
            "x-api-key": api_key,
            "anthropic-version": version,
            "accept": "application/json",
            "content-type": "application/json",
        }

        try:
            response = httpx.get(
                f"{base_url}/v1/models",
                headers=headers,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AppException(
                "Provider request timed out.",
                status_code=504,
                code="provider_timeout",
                details={"provider": "anthropic"},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise_provider_http_exception(provider="anthropic", exc=exc)
        except httpx.HTTPError as exc:
            raise AppException(
                "Failed to communicate with provider.",
                status_code=502,
                code="provider_network_error",
                details={"provider": "anthropic"},
            ) from exc

        payload = response.json()
        if not isinstance(payload, dict):
            raise AppException(
                "Provider response is invalid.",
                status_code=502,
                code="provider_invalid_response",
                details={"provider": "anthropic"},
            )
        items = payload.get("data")
        if not isinstance(items, list):
            raise AppException(
                "Provider response has no models list.",
                status_code=502,
                code="provider_invalid_response",
                details={"provider": "anthropic"},
            )
        return [item for item in items if isinstance(item, dict)]
