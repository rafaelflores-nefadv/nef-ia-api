import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_secret
from app.core.exceptions import AppException
from app.models.operational import DjangoAiProvider, DjangoAiProviderCredential
from app.repositories.operational import ProviderModelRepository, ProviderRepository
from app.services.providers.anthropic_client import AnthropicAdminClient
from app.services.providers.openai_client import OpenAIAdminClient
from app.services.providers.provider_resolution import (
    SUPPORTED_DISCOVERY_PROVIDER_SLUGS,
    resolve_discovery_provider_slug,
)


class ProviderModelDiscoveryService:
    SUPPORTED_PROVIDER_SLUGS = set(SUPPORTED_DISCOVERY_PROVIDER_SLUGS)

    def __init__(self, session: Session) -> None:
        self.session = session
        self.providers = ProviderRepository(session)
        self.models = ProviderModelRepository(session)
        self.settings = get_settings()
        self.openai_client = OpenAIAdminClient()
        self.anthropic_client = AnthropicAdminClient()

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
        canonical_provider_slug, raw_models = self.fetch_raw_models(
            provider_slug=provider.slug,
            provider_id=provider.id,
            api_key=api_key,
            config_json=credential.config_json or {},
        )
        registered_slugs = {item.model_slug.lower() for item in self.models.list_by_provider(provider.id)}

        normalized: list[dict[str, Any]] = []
        seen_slugs: set[str] = set()
        for item in raw_models:
            normalized_item = self._normalize_provider_model_item(
                item,
                canonical_provider_slug=canonical_provider_slug,
            )
            if normalized_item is None:
                continue

            model_slug = str(normalized_item["model_slug"])
            if model_slug in seen_slugs:
                continue
            seen_slugs.add(model_slug)

            normalized_item.update(
                {
                    "provider_id": provider.id,
                    "provider_slug": provider.slug,
                    "is_registered": model_slug in registered_slugs,
                }
            )
            normalized.append(normalized_item)

        normalized.sort(key=lambda row: str(row["model_slug"]))
        return normalized

    def fetch_raw_models(
        self,
        *,
        provider_slug: str,
        provider_id: uuid.UUID | None,
        api_key: str,
        config_json: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        canonical_provider_slug = self._resolve_supported_provider_slug_or_422(
            provider_slug=provider_slug,
            provider_id=provider_id,
        )
        raw_models = self._fetch_provider_models(
            canonical_provider_slug=canonical_provider_slug,
            api_key=api_key,
            config_json=config_json,
        )
        return canonical_provider_slug, raw_models

    def _fetch_provider_models(
        self,
        *,
        canonical_provider_slug: str,
        api_key: str,
        config_json: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if canonical_provider_slug == "openai":
            return self._fetch_openai_available_models(
                api_key=api_key,
                config_json=config_json,
            )
        if canonical_provider_slug == "anthropic":
            return self._fetch_anthropic_available_models(
                api_key=api_key,
                config_json=config_json,
            )
        raise AppException(
            "Provider model discovery is not supported for this provider yet.",
            status_code=422,
            code="provider_discovery_not_supported",
            details={
                "provider_slug": canonical_provider_slug,
                "supported_provider_slugs": sorted(self.SUPPORTED_PROVIDER_SLUGS),
            },
        )

    def _fetch_openai_available_models(
        self,
        *,
        api_key: str,
        config_json: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self.openai_client.list_models(
            api_key=api_key,
            config_json=config_json,
            default_timeout_seconds=self.settings.provider_timeout_seconds,
        )

    def _fetch_anthropic_available_models(
        self,
        *,
        api_key: str,
        config_json: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self.anthropic_client.list_models(
            api_key=api_key,
            config_json=config_json,
            anthropic_version=self.settings.anthropic_api_version,
            default_timeout_seconds=self.settings.provider_timeout_seconds,
        )

    def _resolve_supported_provider_slug_or_422(
        self,
        *,
        provider_slug: str,
        provider_id: uuid.UUID | None,
    ) -> str:
        canonical_provider_slug = resolve_discovery_provider_slug(provider_slug)
        if canonical_provider_slug is not None:
            return canonical_provider_slug

        details: dict[str, Any] = {
            "provider_slug": provider_slug,
            "supported_provider_slugs": sorted(self.SUPPORTED_PROVIDER_SLUGS),
        }
        if provider_id is not None:
            details["provider_id"] = str(provider_id)
        raise AppException(
            "Provider model discovery is not supported for this provider yet.",
            status_code=422,
            code="provider_discovery_not_supported",
            details=details,
        )

    def _normalize_provider_model_item(
        self,
        item: dict[str, Any],
        *,
        canonical_provider_slug: str,
    ) -> dict[str, Any] | None:
        if canonical_provider_slug == "openai":
            return self._normalize_openai_model_item(item)
        if canonical_provider_slug == "anthropic":
            return self._normalize_anthropic_model_item(item)
        return None

    def _normalize_openai_model_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        provider_model_id = str(item.get("id") or "").strip()
        model_slug = self._normalize_slug(provider_model_id)
        if not model_slug:
            return None

        model_name = str(item.get("id") or item.get("name") or model_slug).strip() or model_slug
        owned_by = str(item.get("owned_by") or "").strip()
        description = "Modelo descoberto via API do provider."
        if owned_by:
            description = f"Modelo descoberto via API do provider (owner: {owned_by})."

        context_limit = self._coerce_int(item.get("context_window"))
        return {
            "provider_model_id": provider_model_id or model_slug,
            "model_name": model_name,
            "model_slug": model_slug,
            "context_limit": context_limit,
            "context_window": context_limit,
            "cost_input_per_1k_tokens": None,
            "cost_output_per_1k_tokens": None,
            "description": description,
            "supports_vision": self._coerce_bool(item.get("supports_vision")),
            "supports_reasoning": self._coerce_bool(item.get("supports_reasoning")),
            "supports_thinking": self._coerce_bool(item.get("supports_thinking")),
            "raw_payload": item,
        }

    def _normalize_anthropic_model_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        provider_model_id = str(item.get("id") or "").strip()
        model_slug = self._normalize_slug(provider_model_id)
        if not model_slug:
            return None

        model_name = (
            str(item.get("display_name") or item.get("name") or provider_model_id).strip() or model_slug
        )
        capabilities = item.get("capabilities")
        capabilities_json = capabilities if isinstance(capabilities, dict) else {}

        context_limit = self._coerce_int(
            item.get("context_window")
            or item.get("max_context_tokens")
            or item.get("max_input_tokens")
            or capabilities_json.get("context_window")
            or capabilities_json.get("max_context_tokens")
        )
        supports_vision = self._coerce_bool(
            capabilities_json.get("vision")
            or capabilities_json.get("supports_vision")
            or item.get("supports_vision")
        )
        supports_reasoning = self._coerce_bool(
            capabilities_json.get("reasoning")
            or capabilities_json.get("supports_reasoning")
            or item.get("supports_reasoning")
        )
        supports_thinking = self._coerce_bool(
            capabilities_json.get("thinking")
            or capabilities_json.get("supports_thinking")
            or item.get("supports_thinking")
        )

        description = "Modelo descoberto via API nativa Anthropic."
        model_type = str(item.get("type") or "").strip()
        if model_type and model_type != "model":
            description = f"Modelo descoberto via API nativa Anthropic (type: {model_type})."

        return {
            "provider_model_id": provider_model_id or model_slug,
            "model_name": model_name,
            "model_slug": model_slug,
            "context_limit": context_limit,
            "context_window": context_limit,
            "cost_input_per_1k_tokens": None,
            "cost_output_per_1k_tokens": None,
            "description": description,
            "supports_vision": supports_vision,
            "supports_reasoning": supports_reasoning,
            "supports_thinking": supports_thinking,
            "raw_payload": item,
        }

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

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if value in {None, ""}:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "sim"}:
                return True
            if normalized in {"0", "false", "no", "nao"}:
                return False
            return None
        if isinstance(value, (int, float)):
            return bool(value)
        return None
