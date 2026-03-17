import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational import DjangoAiProvider, DjangoAiProviderCredential


class ProviderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, provider: DjangoAiProvider) -> DjangoAiProvider:
        self.session.add(provider)
        self.session.flush()
        return provider

    def list_all(self) -> list[DjangoAiProvider]:
        stmt = select(DjangoAiProvider).order_by(DjangoAiProvider.created_at.desc())
        return list(self.session.execute(stmt).scalars().all())

    def get_by_id(self, provider_id: uuid.UUID) -> DjangoAiProvider | None:
        stmt = select(DjangoAiProvider).where(DjangoAiProvider.id == provider_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_slug(self, slug: str) -> DjangoAiProvider | None:
        stmt = select(DjangoAiProvider).where(DjangoAiProvider.slug == slug)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_active(self) -> list[DjangoAiProvider]:
        stmt = select(DjangoAiProvider).where(DjangoAiProvider.is_active.is_(True)).order_by(DjangoAiProvider.slug.asc())
        return list(self.session.execute(stmt).scalars().all())

    def get_active_by_slug(self, slug: str) -> DjangoAiProvider | None:
        stmt = select(DjangoAiProvider).where(
            DjangoAiProvider.slug == slug,
            DjangoAiProvider.is_active.is_(True),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_credentials(self, provider_id: uuid.UUID) -> list[DjangoAiProviderCredential]:
        stmt = select(DjangoAiProviderCredential).where(DjangoAiProviderCredential.provider_id == provider_id)
        return list(self.session.execute(stmt).scalars().all())

    def get_active_credential(self, provider_id: uuid.UUID) -> DjangoAiProviderCredential | None:
        stmt = (
            select(DjangoAiProviderCredential)
            .where(
                DjangoAiProviderCredential.provider_id == provider_id,
                DjangoAiProviderCredential.is_active.is_(True),
            )
            .order_by(DjangoAiProviderCredential.updated_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()
