import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational import DjangoAiProviderModel


class ProviderModelRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, model: DjangoAiProviderModel) -> DjangoAiProviderModel:
        self.session.add(model)
        self.session.flush()
        return model

    def get_by_id(self, model_id: uuid.UUID) -> DjangoAiProviderModel | None:
        stmt = select(DjangoAiProviderModel).where(DjangoAiProviderModel.id == model_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_provider(self, provider_id: uuid.UUID) -> list[DjangoAiProviderModel]:
        stmt = (
            select(DjangoAiProviderModel)
            .where(DjangoAiProviderModel.provider_id == provider_id)
            .order_by(DjangoAiProviderModel.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_by_slug(self, provider_id: uuid.UUID, model_slug: str) -> DjangoAiProviderModel | None:
        stmt = select(DjangoAiProviderModel).where(
            DjangoAiProviderModel.provider_id == provider_id,
            DjangoAiProviderModel.model_slug == model_slug,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_model_slug(self, model_slug: str) -> DjangoAiProviderModel | None:
        stmt = select(DjangoAiProviderModel).where(DjangoAiProviderModel.model_slug == model_slug)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_active_by_slug(self, provider_id: uuid.UUID, model_slug: str) -> DjangoAiProviderModel | None:
        stmt = select(DjangoAiProviderModel).where(
            DjangoAiProviderModel.provider_id == provider_id,
            DjangoAiProviderModel.model_slug == model_slug,
            DjangoAiProviderModel.is_active.is_(True),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def exists_active_for_provider(self, provider_id: uuid.UUID) -> bool:
        stmt = (
            select(DjangoAiProviderModel.id)
            .where(
                DjangoAiProviderModel.provider_id == provider_id,
                DjangoAiProviderModel.is_active.is_(True),
            )
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none() is not None

    def get_first_active(self, provider_id: uuid.UUID) -> DjangoAiProviderModel | None:
        stmt = (
            select(DjangoAiProviderModel)
            .where(
                DjangoAiProviderModel.provider_id == provider_id,
                DjangoAiProviderModel.is_active.is_(True),
            )
            .order_by(DjangoAiProviderModel.updated_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()
