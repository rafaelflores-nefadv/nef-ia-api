from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational import DjangoAiExecutionInputFile


class ExecutionInputFileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, model: DjangoAiExecutionInputFile) -> DjangoAiExecutionInputFile:
        self.session.add(model)
        self.session.flush()
        return model

    def list_by_execution_id(self, execution_id: UUID) -> list[DjangoAiExecutionInputFile]:
        stmt = (
            select(DjangoAiExecutionInputFile)
            .where(DjangoAiExecutionInputFile.execution_id == execution_id)
            .order_by(
                DjangoAiExecutionInputFile.order_index.asc(),
                DjangoAiExecutionInputFile.created_at.asc(),
            )
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_primary_by_execution_id(self, execution_id: UUID) -> DjangoAiExecutionInputFile | None:
        stmt = (
            select(DjangoAiExecutionInputFile)
            .where(
                DjangoAiExecutionInputFile.execution_id == execution_id,
                DjangoAiExecutionInputFile.role == "primary",
            )
            .order_by(
                DjangoAiExecutionInputFile.order_index.asc(),
                DjangoAiExecutionInputFile.created_at.asc(),
            )
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_request_file_id(self, request_file_id: UUID) -> list[DjangoAiExecutionInputFile]:
        stmt = (
            select(DjangoAiExecutionInputFile)
            .where(DjangoAiExecutionInputFile.request_file_id == request_file_id)
            .order_by(DjangoAiExecutionInputFile.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())
