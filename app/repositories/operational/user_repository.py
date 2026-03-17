import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.operational import DjangoAiUser


class AdminUserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_email(self, email: str) -> DjangoAiUser | None:
        stmt = select(DjangoAiUser).options(joinedload(DjangoAiUser.role)).where(DjangoAiUser.email == email)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_id(self, user_id: uuid.UUID) -> DjangoAiUser | None:
        stmt = select(DjangoAiUser).options(joinedload(DjangoAiUser.role)).where(DjangoAiUser.id == user_id)
        return self.session.execute(stmt).scalar_one_or_none()
