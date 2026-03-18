import uuid
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_secret
from app.core.exceptions import AppException
from app.models.operational import DjangoAiProvider, DjangoAiProviderCredential
from app.repositories.operational import ProviderModelRepository, ProviderRepository


class ProviderModelDiscoveryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.providers = ProviderRepository(session)
        self.models = ProviderModelRepository(session)
        self.settings = get_settings()

    def list_available_models(self, *, provider_id: uuid.UUID) -> list[dict[str, Any]]:
        provider = self._get_provider_or_404(provider_id)
        if not provider.is_active:
            raise AppException(
                "Configured provider is inactive in the operational catalog.",
                status_code=422,
                code="provider_inactive",
                details={"provider_id": str(provider.id), "provider_slug": provider.slug},
            )

        credential = self._get_active_credential_or_422(provider)
        api_key = self._decrypt_credential_or_422(credential)

        if provider.slug != "openai":
            raise AppException(
                "Provider model discovery is not supported for this provider yet.",
                status_code=422,
                code="provider_discovery_not_supported",
                details={"provider_slug": provider.slug, "provider_id": str(provider.id)},
            )

        raw_models = self._fetch_openai_available_models(
            api_key=api_key,
            config_json=credential.config_json or {},
        )
        registered_slugs = {item.model_slug.lower() for item in self.models.list_by_provider(provider.id)}

        normalized: list[dict[str, Any]] = []
        seen_slugs: set[str] = set()
        for item in raw_models:
            model_slug = self._normalize_slug(str(item.get("id") or ""))
            if not model_slug or model_slug in seen_slugs:
                continue
            seen_slugs.add(model_slug)

            model_name = str(item.get("id") or model_slug).strip()
            owned_by = str(item.get("owned_by") or "").strip()
            description = "Modelo descoberto via API do provider."
            if owned_by:
                description = f"Modelo descoberto via API do provider (owner: {owned_by})."

            normalized.append(
                {
                    "provider_id": provider.id,
                    "provider_slug": provider.slug,
                    "provider_model_id": str(item.get("id") or model_slug),
                    "model_name": model_name,
                    "model_slug": model_slug,
                    "context_limit": None,
                    "cost_input_per_1k_tokens": None,
                    "cost_output_per_1k_tokens": None,
                    "description": description,
                    "is_registered": model_slug in registered_slugs,
                }
            )

        normalized.sort(key=lambda row: str(row["model_slug"]))
        return normalized

    def _fetch_openai_available_models(
        self,
        *,
        api_key: str,
        config_json: dict[str, Any],
    ) -> list[dict[str, Any]]:
        base_url = str(config_json.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        timeout_seconds = int(config_json.get("timeout_seconds") or self.settings.provider_timeout_seconds)
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
            raise AppException(
                "Provider returned an error response.",
                status_code=502,
                code="provider_http_error",
                details={"provider": "openai", "status_code": exc.response.status_code},
            ) from exc
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
        return [row for row in items if isinstance(row, dict)]

    def _get_provider_or_404(self, provider_id: uuid.UUID) -> DjangoAiProvider:
        provider = self.providers.get_by_id(provider_id)
        if provider is None:
            raise AppException(
                "Provider not found.",
                status_code=404,
                code="provider_not_found",
                details={"provider_id": str(provider_id)},
            )
        return provider

    def _get_active_credential_or_422(
        self,
        provider: DjangoAiProvider,
    ) -> DjangoAiProviderCredential:
        credential = self.providers.get_active_credential(provider.id)
        if credential is None:
            raise AppException(
                "No active credential found for configured provider.",
                status_code=422,
                code="provider_credential_not_found",
                details={"provider_slug": provider.slug, "provider_id": str(provider.id)},
            )
        return credential

    @staticmethod
    def _decrypt_credential_or_422(credential: DjangoAiProviderCredential) -> str:
        api_key = decrypt_secret(credential.encrypted_api_key).strip()
        if not api_key:
            raise AppException(
                "Provider credential is invalid.",
                status_code=422,
                code="provider_credential_invalid",
                details={"credential_id": str(credential.id)},
            )
        return api_key

    @staticmethod
    def _normalize_slug(value: str) -> str:
        return value.strip().lower()
