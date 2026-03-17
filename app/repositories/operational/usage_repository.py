import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational import DjangoAiProviderUsage


class ProviderUsageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_by_execution(self, execution_id: uuid.UUID) -> list[DjangoAiProviderUsage]:
        stmt = select(DjangoAiProviderUsage).where(DjangoAiProviderUsage.execution_id == execution_id)
        return list(self.session.execute(stmt).scalars().all())

    def add(self, usage: DjangoAiProviderUsage) -> DjangoAiProviderUsage:
        self.session.add(usage)
        self.session.flush()
        return usage
