from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational import DjangoAiRequestFile


class RequestFileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, model: DjangoAiRequestFile) -> DjangoAiRequestFile:
        self.session.add(model)
        self.session.flush()
        return model

    def get_by_id(self, file_id: UUID) -> DjangoAiRequestFile | None:
        stmt = select(DjangoAiRequestFile).where(DjangoAiRequestFile.id == file_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_request_id(self, analysis_request_id: UUID) -> list[DjangoAiRequestFile]:
        stmt = select(DjangoAiRequestFile).where(DjangoAiRequestFile.analysis_request_id == analysis_request_id)
        return list(self.session.execute(stmt).scalars().all())

