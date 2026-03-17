from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.jwt import create_admin_jwt, decode_admin_jwt
from app.core.security import verify_password
from app.models.operational import DjangoAiAuditLog, DjangoAiUser
from app.repositories.operational import AdminUserRepository, AuditLogRepository


@dataclass(slots=True)
class AdminLoginResult:
    user: DjangoAiUser
    access_token: str
    expires_at: datetime


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = AdminUserRepository(session)
        self.audit = AuditLogRepository(session)

    def login_admin(self, *, email: str, password: str, ip_address: str | None = None) -> AdminLoginResult:
        user = self.users.get_by_email(email)
        if user is None or not user.is_active:
            raise AppException(
                "Invalid credentials.",
                status_code=401,
                code="invalid_credentials",
            )
        if not verify_password(password, user.password_hash):
            raise AppException(
                "Invalid credentials.",
                status_code=401,
                code="invalid_credentials",
            )

        role_name = user.role.name if user.role else "unknown"
        jwt_token, expires_at = create_admin_jwt(user_id=str(user.id), role=role_name)

        self.audit.add(
            DjangoAiAuditLog(
                action_type="user_login",
                entity_type="django_ai_users",
                entity_id=str(user.id),
                performed_by_user_id=user.id,
                changes_json={"email": user.email, "role": role_name},
                ip_address=ip_address,
            )
        )
        self.session.commit()
        return AdminLoginResult(user=user, access_token=jwt_token, expires_at=expires_at)

    def get_user_from_admin_jwt(self, jwt_token: str) -> DjangoAiUser:
        payload = decode_admin_jwt(jwt_token)
        user_id = payload.get("sub")
        if user_id is None:
            raise AppException(
                "Invalid administrative token payload.",
                status_code=401,
                code="invalid_admin_token_payload",
            )

        user = self.users.get_by_id(UUID(user_id))
        if user is None or not user.is_active:
            raise AppException(
                "Administrative user not found or inactive.",
                status_code=401,
                code="admin_user_not_available",
            )
        return user
