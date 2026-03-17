from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.shared import AnalysisExecution, AnalysisRequest


class SharedAnalysisRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_request_by_id(self, analysis_request_id: UUID) -> AnalysisRequest | None:
        stmt = select(AnalysisRequest).where(AnalysisRequest.id == analysis_request_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_execution_by_id(self, execution_id: UUID) -> AnalysisExecution | None:
        stmt = select(AnalysisExecution).where(AnalysisExecution.id == execution_id)
        return self.session.execute(stmt).scalar_one_or_none()

