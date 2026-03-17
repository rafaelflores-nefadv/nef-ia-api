from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_secret
from app.core.exceptions import AppException
from app.integrations.providers import AiProviderClient, ProviderRegistry
from app.models.operational import DjangoAiProvider, DjangoAiProviderCredential, DjangoAiProviderModel
from app.repositories.operational import ProviderModelRepository, ProviderRepository

settings = get_settings()


@dataclass(slots=True)
class ProviderRuntimeSelection:
    provider: DjangoAiProvider
    model: DjangoAiProviderModel
    credential: DjangoAiProviderCredential
    client: AiProviderClient


class ProviderService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.providers = ProviderRepository(session)
        self.models = ProviderModelRepository(session)
        self.registry = ProviderRegistry()

    def resolve_runtime(
        self,
        *,
        provider_slug: str,
        model_slug: str,
    ) -> ProviderRuntimeSelection:
        provider = self.providers.get_by_slug(provider_slug)
        if provider is None:
            raise AppException(
                "Configured provider does not exist in the operational catalog.",
                status_code=404,
                code="provider_not_found",
                details={"provider_slug": provider_slug},
            )

        if not provider.is_active:
            raise AppException(
                "Configured provider is inactive in the operational catalog.",
                status_code=422,
                code="provider_inactive",
                details={"provider_slug": provider_slug},
            )

        credential = self.providers.get_active_credential(provider.id)
        if credential is None:
            raise AppException(
                "No active credential found for configured provider.",
                status_code=422,
                code="provider_credential_not_found",
                details={"provider_slug": provider_slug, "provider_id": str(provider.id)},
            )

        model_for_provider = self.models.get_by_slug(provider.id, model_slug)
        if model_for_provider is None:
            model = self.models.get_by_model_slug(model_slug)
            if model is None:
                raise AppException(
                    "Configured model does not exist in the operational catalog.",
                    status_code=404,
                    code="provider_model_not_found",
                    details={"provider_slug": provider_slug, "model_slug": model_slug},
                )
            raise AppException(
                "Configured model does not belong to configured provider.",
                status_code=422,
                code="provider_model_mismatch",
                details={"provider_slug": provider_slug, "model_slug": model_slug},
            )

        if not model_for_provider.is_active:
            raise AppException(
                "Configured model is inactive in the operational catalog.",
                status_code=422,
                code="provider_model_inactive",
                details={"provider_slug": provider_slug, "model_slug": model_slug},
            )

        api_key = self._decrypt_api_key(credential.encrypted_api_key)
        if not api_key:
            raise AppException(
                "Provider credential is invalid.",
                status_code=422,
                code="provider_credential_invalid",
                details={"provider_id": str(provider.id)},
            )

        client = self.registry.build(
            provider_slug=provider.slug,
            api_key=api_key,
            timeout_seconds=settings.provider_timeout,
        )
        return ProviderRuntimeSelection(
            provider=provider,
            model=model_for_provider,
            credential=credential,
            client=client,
        )

    @staticmethod
    def _decrypt_api_key(encrypted_api_key: str) -> str:
        return decrypt_secret(encrypted_api_key)
