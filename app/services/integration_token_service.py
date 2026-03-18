from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.security import generate_integration_token, hash_token
from app.models.operational import DjangoAiAuditLog, DjangoAiIntegrationToken, DjangoAiUser
from app.repositories.operational import AdminUserRepository, AuditLogRepository, IntegrationTokenRepository


@dataclass(slots=True)
class IntegrationTokenValidationResult:
    token: DjangoAiIntegrationToken
    user: DjangoAiUser


class IntegrationTokenService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tokens = IntegrationTokenRepository(session)
        self.users = AdminUserRepository(session)
        self.audit = AuditLogRepository(session)

    def create_token(
        self,
        *,
        name: str,
        created_by_user_id: UUID,
        ip_address: str | None = None,
    ) -> tuple[DjangoAiIntegrationToken, str]:
        raw_token = generate_integration_token()
        token_model = DjangoAiIntegrationToken(
            name=name.strip(),
            token_hash=hash_token(raw_token),
            is_active=True,
            last_used_at=None,
            created_by_user_id=created_by_user_id,
        )
        self.tokens.add(token_model)

        self.audit.add(
            DjangoAiAuditLog(
                action_type="integration_token_created",
                entity_type="django_ai_integration_tokens",
                entity_id=str(token_model.id),
                performed_by_user_id=created_by_user_id,
                changes_json={"name": token_model.name, "is_active": token_model.is_active},
                ip_address=ip_address,
            )
        )
        self.session.commit()
        self.session.refresh(token_model)
        return token_model, raw_token

    def list_tokens(self) -> list[DjangoAiIntegrationToken]:
        return self.tokens.list_all()

    def deactivate_token(
        self,
        *,
        token_id: UUID,
        actor_user_id: UUID,
        ip_address: str | None = None,
    ) -> DjangoAiIntegrationToken:
        token_model = self.tokens.deactivate(token_id)
        if token_model is None:
            raise AppException("Integration token not found.", status_code=404, code="integration_token_not_found")

        self.audit.add(
            DjangoAiAuditLog(
                action_type="integration_token_deactivated",
                entity_type="django_ai_integration_tokens",
                entity_id=str(token_model.id),
                performed_by_user_id=actor_user_id,
                changes_json={"is_active": False},
                ip_address=ip_address,
            )
        )
        self.session.commit()
        self.session.refresh(token_model)
        return token_model

    def validate_token(self, raw_token: str) -> IntegrationTokenValidationResult:
        token_model = self.tokens.get_by_hash(hash_token(raw_token))
        if token_model is None:
            raise AppException(
                "Invalid integration token.",
                status_code=401,
                code="invalid_integration_token",
            )
        if not token_model.is_active:
            raise AppException(
                "Integration token is deactivated.",
                status_code=401,
                code="deactivated_integration_token",
            )

        user = self.users.get_by_id(token_model.created_by_user_id)
        if user is None or not user.is_active:
            raise AppException(
                "Integration token owner is unavailable.",
                status_code=401,
                code="integration_token_owner_unavailable",
            )

        return IntegrationTokenValidationResult(token=token_model, user=user)

    def touch_last_used(self, *, token_id: UUID) -> None:
        updated = self.tokens.touch_last_used(token_id)
        if updated is None:
            return
        self.session.commit()

    @staticmethod
    def mask_token_hash(token_hash: str) -> str:
        normalized = token_hash.strip()
        if len(normalized) <= 12:
            return normalized
        return f"{normalized[:8]}...{normalized[-4:]}"

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(timezone.utc)
