from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational import DjangoAiExecutionFile


class ExecutionFileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, model: DjangoAiExecutionFile) -> DjangoAiExecutionFile:
        self.session.add(model)
        self.session.flush()
        return model

    def get_by_id(self, file_id: UUID) -> DjangoAiExecutionFile | None:
        stmt = select(DjangoAiExecutionFile).where(DjangoAiExecutionFile.id == file_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_execution_id(self, execution_id: UUID) -> list[DjangoAiExecutionFile]:
        stmt = select(DjangoAiExecutionFile).where(DjangoAiExecutionFile.execution_id == execution_id)
        return list(self.session.execute(stmt).scalars().all())

