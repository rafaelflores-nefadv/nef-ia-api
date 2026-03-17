import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational import DjangoAiProviderCredential


class ProviderCredentialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, credential: DjangoAiProviderCredential) -> DjangoAiProviderCredential:
        self.session.add(credential)
        self.session.flush()
        return credential

    def get_by_id(self, credential_id: uuid.UUID) -> DjangoAiProviderCredential | None:
        stmt = select(DjangoAiProviderCredential).where(DjangoAiProviderCredential.id == credential_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_provider(self, provider_id: uuid.UUID) -> list[DjangoAiProviderCredential]:
        stmt = (
            select(DjangoAiProviderCredential)
            .where(DjangoAiProviderCredential.provider_id == provider_id)
            .order_by(DjangoAiProviderCredential.updated_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_by_name(self, *, provider_id: uuid.UUID, credential_name: str) -> DjangoAiProviderCredential | None:
        stmt = select(DjangoAiProviderCredential).where(
            DjangoAiProviderCredential.provider_id == provider_id,
            DjangoAiProviderCredential.credential_name == credential_name,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_active_by_provider(self, provider_id: uuid.UUID) -> list[DjangoAiProviderCredential]:
        stmt = (
            select(DjangoAiProviderCredential)
            .where(
                DjangoAiProviderCredential.provider_id == provider_id,
                DjangoAiProviderCredential.is_active.is_(True),
            )
            .order_by(DjangoAiProviderCredential.updated_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())
