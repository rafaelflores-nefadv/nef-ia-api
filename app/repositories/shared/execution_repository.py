from datetime import datetime, timezone
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.shared import AnalysisExecution


class SharedExecutionRepository:
    """
    Access layer for shared `analysis_executions`.
    Source of truth remains in the general system database.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, analysis_request_id: UUID, status: str) -> AnalysisExecution:
        execution = AnalysisExecution(
            id=uuid.uuid4(),
            analysis_request_id=analysis_request_id,
            status=status,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(execution)
        self.session.flush()
        return execution

    def get_by_id(self, execution_id: UUID) -> AnalysisExecution | None:
        stmt = select(AnalysisExecution).where(AnalysisExecution.id == execution_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_analysis_request_id(self, analysis_request_id: UUID) -> list[AnalysisExecution]:
        stmt = (
            select(AnalysisExecution)
            .where(AnalysisExecution.analysis_request_id == analysis_request_id)
            .order_by(AnalysisExecution.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def update_status(self, *, execution_id: UUID, status: str) -> AnalysisExecution | None:
        execution = self.get_by_id(execution_id)
        if execution is None:
            return None
        execution.status = status
        self.session.flush()
        return execution
