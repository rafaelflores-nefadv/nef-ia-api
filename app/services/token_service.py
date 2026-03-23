from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.security import generate_api_token, hash_token
from app.models.operational import (
    DjangoAiApiToken,
    DjangoAiApiTokenLog,
    DjangoAiApiTokenPermission,
    DjangoAiAuditLog,
    DjangoAiIntegrationToken,
)
from app.repositories.operational import ApiTokenRepository, AuditLogRepository, IntegrationTokenRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TokenValidationResult:
    token: DjangoAiApiToken
    permissions: list[DjangoAiApiTokenPermission]


def check_token_permission(
    *,
    permissions: list[DjangoAiApiTokenPermission],
    operation: str,
    automation_id: UUID | None = None,
    provider_id: UUID | None = None,
) -> bool:
    if not permissions:
        return False

    for permission in permissions:
        if automation_id and permission.automation_id != automation_id:
            continue
        if permission.provider_id is not None and provider_id is None:
            continue
        if provider_id and permission.provider_id and permission.provider_id != provider_id:
            continue

        if operation == "execution" and permission.allow_execution:
            return True
        if operation == "file_upload" and permission.allow_file_upload:
            return True
        if operation == "file_download" and (permission.allow_file_upload or permission.allow_execution):
            return True
    return False


class ApiTokenService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tokens = ApiTokenRepository(session)
        self.audit = AuditLogRepository(session)

    def create_token(
        self,
        *,
        name: str,
        created_by_user_id: UUID,
        expires_at: datetime | None,
        permissions: list[dict],
        ip_address: str | None = None,
    ) -> tuple[DjangoAiApiToken, str]:
        raw_token = generate_api_token()
        token_hash = hash_token(raw_token)

        token_model = DjangoAiApiToken(
            name=name,
            token_hash=token_hash,
            is_active=True,
            expires_at=expires_at,
            created_by_user_id=created_by_user_id,
        )
        self.tokens.add(token_model)

        for permission in permissions:
            self.tokens.add_permission(
                DjangoAiApiTokenPermission(
                    token_id=token_model.id,
                    automation_id=permission["automation_id"],
                    provider_id=permission.get("provider_id"),
                    allow_execution=permission.get("allow_execution", True),
                    allow_file_upload=permission.get("allow_file_upload", False),
                )
            )

        self.audit.add(
            DjangoAiAuditLog(
                action_type="token_created",
                entity_type="django_ai_api_tokens",
                entity_id=str(token_model.id),
                performed_by_user_id=created_by_user_id,
                changes_json={
                    "name": token_model.name,
                    "expires_at": token_model.expires_at.isoformat() if token_model.expires_at else None,
                    "permissions_count": len(permissions),
                },
                ip_address=ip_address,
            )
        )
        self.session.commit()
        self.session.refresh(token_model)
        return token_model, raw_token

    def list_tokens(self) -> list[DjangoAiApiToken]:
        return self.tokens.list_all()

    def revoke_token(self, *, token_id: UUID, actor_user_id: UUID, ip_address: str | None = None) -> DjangoAiApiToken:
        token_model = self.tokens.revoke(token_id)
        if token_model is None:
            raise AppException("Token not found.", status_code=404, code="token_not_found")

        self.audit.add(
            DjangoAiAuditLog(
                action_type="token_revoked",
                entity_type="django_ai_api_tokens",
                entity_id=str(token_model.id),
                performed_by_user_id=actor_user_id,
                changes_json={"is_active": False},
                ip_address=ip_address,
            )
        )
        self.session.commit()
        self.session.refresh(token_model)
        return token_model

    def delete_token(self, *, token_id: UUID, actor_user_id: UUID, ip_address: str | None = None) -> None:
        token_model = self.tokens.get_by_id(token_id)
        if token_model is None:
            raise AppException("Token not found.", status_code=404, code="token_not_found")

        deleted = self.tokens.delete(token_id)
        if not deleted:
            raise AppException("Token not found.", status_code=404, code="token_not_found")

        self.audit.add(
            DjangoAiAuditLog(
                action_type="token_deleted",
                entity_type="django_ai_api_tokens",
                entity_id=str(token_id),
                performed_by_user_id=actor_user_id,
                changes_json={"deleted": True},
                ip_address=ip_address,
            )
        )
        self.session.commit()

    def validate_token(self, raw_token: str) -> TokenValidationResult:
        normalized_token = self._normalize_raw_token(raw_token)
        token_hash = hash_token(normalized_token)
        received_prefix = self._extract_token_prefix(normalized_token)
        lookup_order = self._lookup_order_for_prefix(received_prefix)

        integration_repo = IntegrationTokenRepository(self.session)
        token_model: DjangoAiApiToken | None = None
        token_source: str | None = None
        integration_token_found = False

        for source in lookup_order:
            if source == "api":
                token_model = self.tokens.get_by_hash(token_hash)
                if token_model is not None:
                    token_source = "api"
                    break
                continue

            integration_token = integration_repo.get_by_hash(token_hash)
            integration_token_found = integration_token is not None
            if integration_token is None:
                continue
            if not integration_token.is_active:
                logger.warning(
                    "[AUTH DEBUG] received_token_masked=%s received_token_prefix=%s token_hash_prefix=%s "
                    "token_found_in_db=true integration_token_found=true reason=integration_token_revoked",
                    self._mask_token(normalized_token),
                    received_prefix,
                    token_hash[:8],
                )
                raise AppException("API token is revoked.", status_code=401, code="revoked_api_token")
            token_model = self._resolve_api_token_from_integration(
                integration_token=integration_token,
                token_hash=token_hash,
            )
            token_source = "integration"
            break

        if token_model is None:
            logger.warning(
                "[AUTH DEBUG] received_token_masked=%s received_token_prefix=%s token_hash_prefix=%s "
                "token_found_in_db=false integration_token_found=%s reason=token_hash_not_found",
                self._mask_token(normalized_token),
                received_prefix,
                token_hash[:8],
                integration_token_found,
            )
            raise AppException("Invalid API token.", status_code=401, code="invalid_api_token")
        if not token_model.is_active:
            logger.warning(
                "[AUTH DEBUG] received_token_masked=%s received_token_prefix=%s token_found_in_db=true "
                "token_id=%s reason=token_revoked",
                self._mask_token(normalized_token),
                received_prefix,
                token_model.id,
            )
            raise AppException("API token is revoked.", status_code=401, code="revoked_api_token")
        if token_model.expires_at is not None:
            expires_at = token_model.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                logger.warning(
                    "[AUTH DEBUG] received_token_masked=%s received_token_prefix=%s token_found_in_db=true "
                    "token_id=%s reason=token_expired",
                    self._mask_token(normalized_token),
                    received_prefix,
                    token_model.id,
                )
                raise AppException("API token expired.", status_code=401, code="expired_api_token")

        permissions = self.tokens.get_permissions(token_model.id)
        logger.info(
            "[AUTH DEBUG] received_token_prefix=%s token_found_in_db=true token_source=%s "
            "token_id=%s permissions_count=%s reason=validated",
            received_prefix,
            token_source or "api",
            token_model.id,
            len(permissions),
        )
        return TokenValidationResult(token=token_model, permissions=permissions)

    def log_token_usage(
        self,
        *,
        token_id: UUID | None,
        endpoint: str,
        method: str,
        ip_address: str | None,
        user_agent: str | None,
        status_code: int,
        execution_id: UUID | None = None,
    ) -> None:
        self.tokens.add_log(
            DjangoAiApiTokenLog(
                token_id=token_id,
                endpoint=endpoint,
                method=method,
                ip_address=ip_address,
                user_agent=user_agent,
                status_code=status_code,
                execution_id=execution_id,
            )
        )
        self.session.commit()

    @staticmethod
    def _normalize_raw_token(raw_token: str) -> str:
        normalized = raw_token.strip()
        if normalized.lower().startswith("bearer "):
            normalized = normalized[7:].strip()
        if (
            len(normalized) >= 2
            and normalized[0] in {"'", '"'}
            and normalized[-1] == normalized[0]
        ):
            normalized = normalized[1:-1].strip()
        return normalized

    @staticmethod
    def _extract_token_prefix(raw_token: str) -> str:
        normalized = raw_token.strip()
        if not normalized:
            return ""
        segments = normalized.split("_", 2)
        if len(segments) >= 2:
            return f"{segments[0]}_{segments[1]}"
        return segments[0]

    @staticmethod
    def _mask_token(raw_token: str) -> str:
        normalized = raw_token.strip()
        if not normalized:
            return ""
        if len(normalized) <= 10:
            return "***"
        return f"{normalized[:6]}...{normalized[-4:]}"

    @staticmethod
    def _lookup_order_for_prefix(prefix: str) -> tuple[str, str]:
        normalized_prefix = str(prefix or "").strip().lower()
        if normalized_prefix == "ia_int":
            return ("integration", "api")
        if normalized_prefix == "ia_live":
            return ("api", "integration")
        return ("api", "integration")

    def _resolve_api_token_from_integration(
        self,
        *,
        integration_token: DjangoAiIntegrationToken,
        token_hash: str,
    ) -> DjangoAiApiToken:
        existing = self.tokens.get_by_hash(token_hash)
        if existing is not None:
            # Keep mirrored data aligned with integration token state.
            existing.name = self._integration_shadow_name(integration_token.name)
            existing.is_active = bool(integration_token.is_active)
            existing.expires_at = None
            existing.created_by_user_id = integration_token.created_by_user_id
            return existing

        shadow = DjangoAiApiToken(
            id=integration_token.id,
            name=self._integration_shadow_name(integration_token.name),
            token_hash=token_hash,
            is_active=bool(integration_token.is_active),
            expires_at=None,
            created_by_user_id=integration_token.created_by_user_id,
        )
        try:
            self.tokens.add(shadow)
            self.session.commit()
            self.session.refresh(shadow)
            logger.info(
                "[AUTH DEBUG] integration token mirrored into api token table token_id=%s created_by_user_id=%s",
                shadow.id,
                shadow.created_by_user_id,
            )
            return shadow
        except IntegrityError:
            self.session.rollback()
            already = self.tokens.get_by_hash(token_hash)
            if already is not None:
                return already
            raise

    @staticmethod
    def _integration_shadow_name(name: str) -> str:
        normalized = str(name or "").strip()
        if not normalized:
            normalized = "integration-token"
        return f"integration::{normalized}"
