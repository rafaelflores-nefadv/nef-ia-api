import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.core.exceptions import AppException
from app.models.operational import (
    DjangoAiAuditLog,
    DjangoAiProvider,
    DjangoAiProviderCredential,
    DjangoAiProviderModel,
)
from app.repositories.operational import (
    AuditLogRepository,
    ProviderCredentialRepository,
    ProviderModelRepository,
    ProviderRepository,
)

logger = logging.getLogger(__name__)


class ProviderAdminService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.providers = ProviderRepository(session)
        self.models = ProviderModelRepository(session)
        self.credentials = ProviderCredentialRepository(session)
        self.audit = AuditLogRepository(session)

    def list_providers(self) -> list[DjangoAiProvider]:
        return self.providers.list_all()

    def create_provider(
        self,
        *,
        name: str,
        slug: str,
        description: str | None,
        is_active: bool,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> DjangoAiProvider:
        normalized_slug = self._normalize_slug(slug)
        if self.providers.get_by_slug(normalized_slug):
            raise AppException(
                "Provider slug already exists.",
                status_code=409,
                code="provider_slug_conflict",
                details={"provider_slug": normalized_slug},
            )

        provider = DjangoAiProvider(
            name=name.strip(),
            slug=normalized_slug,
            description=description.strip() if description else None,
            is_active=is_active,
        )
        self.providers.add(provider)
        self._register_audit(
            action_type="provider_created",
            entity_type="django_ai_providers",
            entity_id=str(provider.id),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            changes_json={
                "name": provider.name,
                "slug": provider.slug,
                "is_active": provider.is_active,
            },
        )
        self.session.commit()
        self._refresh(provider)
        return provider

    def update_provider(
        self,
        *,
        provider_id: uuid.UUID,
        name: str | None,
        slug: str | None,
        description: str | None,
        is_active: bool | None,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> DjangoAiProvider:
        provider = self._get_provider_or_404(provider_id)
        before_state = {
            "name": provider.name,
            "slug": provider.slug,
            "description": provider.description,
            "is_active": provider.is_active,
        }

        if name is not None:
            provider.name = name.strip()
        if slug is not None:
            normalized_slug = self._normalize_slug(slug)
            existing = self.providers.get_by_slug(normalized_slug)
            if existing and existing.id != provider.id:
                raise AppException(
                    "Provider slug already exists.",
                    status_code=409,
                    code="provider_slug_conflict",
                    details={"provider_slug": normalized_slug},
                )
            provider.slug = normalized_slug
        if description is not None:
            provider.description = description.strip() or None
        if is_active is not None:
            if not is_active:
                deactivated_models = self._deactivate_provider_models(provider.id)
                if deactivated_models:
                    logger.info(
                        "Provider deactivation cascaded to active models.",
                        extra={
                            "event": "provider_model_cascade_deactivate",
                            "provider_id": str(provider.id),
                            "count": deactivated_models,
                        },
                    )
            provider.is_active = is_active

        self._register_audit(
            action_type="provider_updated",
            entity_type="django_ai_providers",
            entity_id=str(provider.id),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            changes_json={
                "before": before_state,
                "after": {
                    "name": provider.name,
                    "slug": provider.slug,
                    "description": provider.description,
                    "is_active": provider.is_active,
                },
            },
        )
        self.session.commit()
        self._refresh(provider)
        return provider

    def activate_provider(
        self,
        *,
        provider_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> DjangoAiProvider:
        provider = self._get_provider_or_404(provider_id)
        provider.is_active = True
        self._register_audit(
            action_type="provider_activated",
            entity_type="django_ai_providers",
            entity_id=str(provider.id),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            changes_json={"is_active": True},
        )
        self.session.commit()
        self._refresh(provider)
        return provider

    def deactivate_provider(
        self,
        *,
        provider_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> DjangoAiProvider:
        provider = self._get_provider_or_404(provider_id)
        provider.is_active = False
        deactivated_models = self._deactivate_provider_models(provider.id)
        self._register_audit(
            action_type="provider_deactivated",
            entity_type="django_ai_providers",
            entity_id=str(provider.id),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            changes_json={
                "is_active": False,
                "deactivated_models_count": deactivated_models,
            },
        )
        self.session.commit()
        self._refresh(provider)
        return provider

    def list_models(self, *, provider_id: uuid.UUID) -> list[DjangoAiProviderModel]:
        self._get_provider_or_404(provider_id)
        return self.models.list_by_provider(provider_id)

    def create_model(
        self,
        *,
        provider_id: uuid.UUID,
        model_name: str,
        model_slug: str,
        context_limit: int,
        cost_input_per_1k_tokens: Decimal,
        cost_output_per_1k_tokens: Decimal,
        is_active: bool,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> DjangoAiProviderModel:
        provider = self._get_provider_or_404(provider_id)
        normalized_slug = self._normalize_slug(model_slug)
        if self.models.get_by_slug(provider_id, normalized_slug):
            raise AppException(
                "Model slug already exists for provider.",
                status_code=409,
                code="provider_model_slug_conflict",
                details={"provider_id": str(provider_id), "model_slug": normalized_slug},
            )
        if is_active and not provider.is_active:
            raise AppException(
                "Cannot activate model while provider is inactive.",
                status_code=422,
                code="provider_inactive",
                details={"provider_id": str(provider_id)},
            )

        model = DjangoAiProviderModel(
            provider_id=provider.id,
            model_name=model_name.strip(),
            model_slug=normalized_slug,
            context_limit=context_limit,
            cost_input_per_1k_tokens=cost_input_per_1k_tokens,
            cost_output_per_1k_tokens=cost_output_per_1k_tokens,
            is_active=is_active,
        )
        self.models.add(model)
        self._register_audit(
            action_type="model_created",
            entity_type="django_ai_provider_models",
            entity_id=str(model.id),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            changes_json={
                "provider_id": str(provider.id),
                "model_slug": model.model_slug,
                "is_active": model.is_active,
            },
        )
        self.session.commit()
        self._refresh(model)
        return model

    def update_model(
        self,
        *,
        model_id: uuid.UUID,
        model_name: str | None,
        model_slug: str | None,
        context_limit: int | None,
        cost_input_per_1k_tokens: Decimal | None,
        cost_output_per_1k_tokens: Decimal | None,
        is_active: bool | None,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> DjangoAiProviderModel:
        model = self._get_model_or_404(model_id)
        provider = self._get_provider_or_404(model.provider_id)
        before_state = {
            "model_name": model.model_name,
            "model_slug": model.model_slug,
            "context_limit": int(model.context_limit),
            "cost_input_per_1k_tokens": str(model.cost_input_per_1k_tokens),
            "cost_output_per_1k_tokens": str(model.cost_output_per_1k_tokens),
            "is_active": model.is_active,
        }

        if model_name is not None:
            model.model_name = model_name.strip()
        if model_slug is not None:
            normalized_slug = self._normalize_slug(model_slug)
            existing = self.models.get_by_slug(model.provider_id, normalized_slug)
            if existing and existing.id != model.id:
                raise AppException(
                    "Model slug already exists for provider.",
                    status_code=409,
                    code="provider_model_slug_conflict",
                    details={"provider_id": str(model.provider_id), "model_slug": normalized_slug},
                )
            model.model_slug = normalized_slug
        if context_limit is not None:
            model.context_limit = context_limit
        if cost_input_per_1k_tokens is not None:
            model.cost_input_per_1k_tokens = cost_input_per_1k_tokens
        if cost_output_per_1k_tokens is not None:
            model.cost_output_per_1k_tokens = cost_output_per_1k_tokens
        if is_active is not None:
            if is_active and not provider.is_active:
                raise AppException(
                    "Cannot activate model while provider is inactive.",
                    status_code=422,
                    code="provider_inactive",
                    details={"provider_id": str(provider.id)},
                )
            model.is_active = is_active

        self._register_audit(
            action_type="model_updated",
            entity_type="django_ai_provider_models",
            entity_id=str(model.id),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            changes_json={
                "before": before_state,
                "after": {
                    "model_name": model.model_name,
                    "model_slug": model.model_slug,
                    "context_limit": int(model.context_limit),
                    "cost_input_per_1k_tokens": str(model.cost_input_per_1k_tokens),
                    "cost_output_per_1k_tokens": str(model.cost_output_per_1k_tokens),
                    "is_active": model.is_active,
                },
            },
        )
        self.session.commit()
        self._refresh(model)
        return model

    def activate_model(
        self,
        *,
        model_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> DjangoAiProviderModel:
        model = self._get_model_or_404(model_id)
        provider = self._get_provider_or_404(model.provider_id)
        if not provider.is_active:
            raise AppException(
                "Cannot activate model while provider is inactive.",
                status_code=422,
                code="provider_inactive",
                details={"provider_id": str(provider.id)},
            )
        model.is_active = True
        self._register_audit(
            action_type="model_activated",
            entity_type="django_ai_provider_models",
            entity_id=str(model.id),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            changes_json={"is_active": True},
        )
        self.session.commit()
        self._refresh(model)
        return model

    def deactivate_model(
        self,
        *,
        model_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> DjangoAiProviderModel:
        model = self._get_model_or_404(model_id)
        model.is_active = False
        self._register_audit(
            action_type="model_deactivated",
            entity_type="django_ai_provider_models",
            entity_id=str(model.id),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            changes_json={"is_active": False},
        )
        self.session.commit()
        self._refresh(model)
        return model

    def list_credentials(self, *, provider_id: uuid.UUID) -> list[DjangoAiProviderCredential]:
        self._get_provider_or_404(provider_id)
        return self.credentials.list_by_provider(provider_id)

    def create_credential(
        self,
        *,
        provider_id: uuid.UUID,
        credential_name: str,
        api_key: str,
        config_json: dict[str, Any],
        is_active: bool,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> DjangoAiProviderCredential:
        provider = self._get_provider_or_404(provider_id)
        existing = self.credentials.get_by_name(provider_id=provider.id, credential_name=credential_name.strip())
        if existing:
            raise AppException(
                "Credential name already exists for provider.",
                status_code=409,
                code="provider_credential_name_conflict",
                details={"provider_id": str(provider.id), "credential_name": credential_name.strip()},
            )
        if not api_key.strip():
            raise AppException("Credential API key cannot be empty.", status_code=422, code="credential_api_key_required")

        credential = DjangoAiProviderCredential(
            provider_id=provider.id,
            credential_name=credential_name.strip(),
            encrypted_api_key=self.encrypt_api_key(api_key),
            config_json=config_json,
            is_active=is_active,
        )
        self.credentials.add(credential)
        self._register_audit(
            action_type="credential_created",
            entity_type="django_ai_provider_credentials",
            entity_id=str(credential.id),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            changes_json={
                "provider_id": str(provider.id),
                "credential_name": credential.credential_name,
                "is_active": credential.is_active,
            },
        )
        self.session.commit()
        self._refresh(credential)
        return credential

    def update_credential(
        self,
        *,
        credential_id: uuid.UUID,
        credential_name: str | None,
        api_key: str | None,
        config_json: dict[str, Any] | None,
        is_active: bool | None,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> DjangoAiProviderCredential:
        credential = self._get_credential_or_404(credential_id)
        before_state = {
            "credential_name": credential.credential_name,
            "is_active": credential.is_active,
            "config_json": credential.config_json,
        }

        if credential_name is not None:
            candidate_name = credential_name.strip()
            existing = self.credentials.get_by_name(provider_id=credential.provider_id, credential_name=candidate_name)
            if existing and existing.id != credential.id:
                raise AppException(
                    "Credential name already exists for provider.",
                    status_code=409,
                    code="provider_credential_name_conflict",
                    details={"provider_id": str(credential.provider_id), "credential_name": candidate_name},
                )
            credential.credential_name = candidate_name

        if api_key is not None:
            if not api_key.strip():
                raise AppException("Credential API key cannot be empty.", status_code=422, code="credential_api_key_required")
            credential.encrypted_api_key = self.encrypt_api_key(api_key)

        if config_json is not None:
            credential.config_json = config_json

        if is_active is not None:
            credential.is_active = is_active

        self._register_audit(
            action_type="credential_updated",
            entity_type="django_ai_provider_credentials",
            entity_id=str(credential.id),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            changes_json={
                "before": before_state,
                "after": {
                    "credential_name": credential.credential_name,
                    "is_active": credential.is_active,
                    "config_json": credential.config_json,
                    "api_key_updated": api_key is not None,
                },
            },
        )
        self.session.commit()
        self._refresh(credential)
        return credential

    def activate_credential(
        self,
        *,
        credential_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> DjangoAiProviderCredential:
        credential = self._get_credential_or_404(credential_id)
        credential.is_active = True
        self._register_audit(
            action_type="credential_activated",
            entity_type="django_ai_provider_credentials",
            entity_id=str(credential.id),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            changes_json={"is_active": True},
        )
        self.session.commit()
        self._refresh(credential)
        return credential

    def deactivate_credential(
        self,
        *,
        credential_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> DjangoAiProviderCredential:
        credential = self._get_credential_or_404(credential_id)
        credential.is_active = False
        self._register_audit(
            action_type="credential_deactivated",
            entity_type="django_ai_provider_credentials",
            entity_id=str(credential.id),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            changes_json={"is_active": False},
        )
        self.session.commit()
        self._refresh(credential)
        return credential

    def build_catalog_status(self) -> dict[str, Any]:
        providers = self.providers.list_all()
        provider_items: list[dict[str, Any]] = []
        global_inconsistencies: list[str] = []

        for provider in providers:
            models = self.models.list_by_provider(provider.id)
            credentials = self.credentials.list_by_provider(provider.id)
            active_models = [item for item in models if item.is_active]
            active_credentials = [item for item in credentials if item.is_active]

            inconsistencies: list[str] = []
            if provider.is_active and not active_models:
                inconsistencies.append("provider_active_without_active_model")
            if provider.is_active and not active_credentials:
                inconsistencies.append("provider_active_without_active_credential")
            if not provider.is_active and active_models:
                inconsistencies.append("active_model_under_inactive_provider")

            slug_counts = Counter(item.model_slug for item in models)
            duplicate_slugs = sorted([slug for slug, count in slug_counts.items() if count > 1])
            if duplicate_slugs:
                inconsistencies.append("duplicate_model_slug_within_provider")

            provider_item = {
                "provider_id": provider.id,
                "name": provider.name,
                "slug": provider.slug,
                "is_active": provider.is_active,
                "total_models": len(models),
                "active_models": len(active_models),
                "total_credentials": len(credentials),
                "active_credentials": len(active_credentials),
                "has_operational_credential": len(active_credentials) > 0,
                "operational_ready": bool(provider.is_active and active_models and active_credentials),
                "inconsistencies": inconsistencies,
            }
            provider_items.append(provider_item)

            for inconsistency in inconsistencies:
                global_inconsistencies.append(f"{provider.slug}:{inconsistency}")

            logger.info(
                "Catalog provider status evaluated.",
                extra={
                    "event": "catalog_provider_status",
                    "provider": provider.slug,
                    "provider_active": provider.is_active,
                    "active_models": len(active_models),
                    "active_credentials": len(active_credentials),
                    "inconsistencies": inconsistencies,
                },
            )

        return {
            "generated_at": datetime.now(timezone.utc),
            "providers": provider_items,
            "global_inconsistencies": global_inconsistencies,
        }

    @staticmethod
    def encrypt_api_key(api_key: str) -> str:
        return encrypt_secret(api_key)

    @staticmethod
    def mask_credential_secret(encrypted_api_key: str) -> str:
        try:
            raw_secret = decrypt_secret(encrypted_api_key)
        except AppException:
            return "********"
        return mask_secret(raw_secret)

    def _deactivate_provider_models(self, provider_id: uuid.UUID) -> int:
        models = self.models.list_by_provider(provider_id)
        changed = 0
        for model in models:
            if model.is_active:
                model.is_active = False
                changed += 1
        return changed

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

    def _get_model_or_404(self, model_id: uuid.UUID) -> DjangoAiProviderModel:
        model = self.models.get_by_id(model_id)
        if model is None:
            raise AppException(
                "Provider model not found.",
                status_code=404,
                code="provider_model_not_found",
                details={"model_id": str(model_id)},
            )
        return model

    def _get_credential_or_404(self, credential_id: uuid.UUID) -> DjangoAiProviderCredential:
        credential = self.credentials.get_by_id(credential_id)
        if credential is None:
            raise AppException(
                "Provider credential not found.",
                status_code=404,
                code="provider_credential_not_found",
                details={"credential_id": str(credential_id)},
            )
        return credential

    def _register_audit(
        self,
        *,
        action_type: str,
        entity_type: str,
        entity_id: str,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
        changes_json: dict[str, Any],
    ) -> None:
        self.audit.add(
            DjangoAiAuditLog(
                action_type=action_type,
                entity_type=entity_type,
                entity_id=entity_id,
                performed_by_user_id=actor_user_id,
                changes_json=changes_json,
                ip_address=ip_address,
            )
        )

    def _refresh(self, instance: Any) -> None:
        refresh = getattr(self.session, "refresh", None)
        if callable(refresh):
            refresh(instance)

    @staticmethod
    def _normalize_slug(value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise AppException("Slug is required.", status_code=422, code="slug_required")
        return normalized
