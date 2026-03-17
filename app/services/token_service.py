from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.security import generate_api_token, hash_token
from app.models.operational import (
    DjangoAiApiToken,
    DjangoAiApiTokenLog,
    DjangoAiApiTokenPermission,
    DjangoAiAuditLog,
)
from app.repositories.operational import ApiTokenRepository, AuditLogRepository


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
        token_model = self.tokens.get_by_hash(hash_token(raw_token))
        if token_model is None:
            raise AppException("Invalid API token.", status_code=401, code="invalid_api_token")
        if not token_model.is_active:
            raise AppException("API token is revoked.", status_code=401, code="revoked_api_token")
        if token_model.expires_at is not None:
            expires_at = token_model.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                raise AppException("API token expired.", status_code=401, code="expired_api_token")

        permissions = self.tokens.get_permissions(token_model.id)
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
