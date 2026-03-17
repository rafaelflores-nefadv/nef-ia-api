import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.operational import (
    DjangoAiApiToken,
    DjangoAiApiTokenLog,
    DjangoAiApiTokenPermission,
)


class ApiTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_hash(self, token_hash: str) -> DjangoAiApiToken | None:
        stmt = select(DjangoAiApiToken).where(DjangoAiApiToken.token_hash == token_hash)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_id(self, token_id: uuid.UUID) -> DjangoAiApiToken | None:
        stmt = select(DjangoAiApiToken).where(DjangoAiApiToken.id == token_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_all(self) -> list[DjangoAiApiToken]:
        stmt = select(DjangoAiApiToken).order_by(DjangoAiApiToken.created_at.desc())
        return list(self.session.execute(stmt).scalars().all())

    def add(self, token: DjangoAiApiToken) -> DjangoAiApiToken:
        self.session.add(token)
        self.session.flush()
        return token

    def add_permission(self, permission: DjangoAiApiTokenPermission) -> DjangoAiApiTokenPermission:
        self.session.add(permission)
        self.session.flush()
        return permission

    def get_permissions(self, token_id: uuid.UUID) -> list[DjangoAiApiTokenPermission]:
        stmt = select(DjangoAiApiTokenPermission).where(DjangoAiApiTokenPermission.token_id == token_id)
        return list(self.session.execute(stmt).scalars().all())

    def add_log(self, log: DjangoAiApiTokenLog) -> DjangoAiApiTokenLog:
        self.session.add(log)
        self.session.flush()
        return log

    def revoke(self, token_id: uuid.UUID) -> DjangoAiApiToken | None:
        token = self.get_by_id(token_id)
        if token is None:
            return None
        token.is_active = False
        token.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        return token

    def delete(self, token_id: uuid.UUID) -> bool:
        stmt = delete(DjangoAiApiToken).where(DjangoAiApiToken.id == token_id)
        result = self.session.execute(stmt)
        return bool(result.rowcount)
