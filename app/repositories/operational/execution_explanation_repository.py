from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational import DjangoAiExecutionExplanation


class ExecutionExplanationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, model: DjangoAiExecutionExplanation) -> DjangoAiExecutionExplanation:
        self.session.add(model)
        self.session.flush()
        return model

    def get_by_execution_id(self, execution_id: UUID) -> DjangoAiExecutionExplanation | None:
        stmt = select(DjangoAiExecutionExplanation).where(DjangoAiExecutionExplanation.execution_id == execution_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert_simple_explanation(
        self,
        *,
        execution_id: UUID,
        simple_explanation: dict | None,
    ) -> DjangoAiExecutionExplanation:
        item = self.get_by_execution_id(execution_id)
        if item is None:
            item = DjangoAiExecutionExplanation(
                execution_id=execution_id,
                simple_explanation=simple_explanation,
            )
            self.add(item)
            return item
        item.simple_explanation = simple_explanation
        self.session.flush()
        return item
