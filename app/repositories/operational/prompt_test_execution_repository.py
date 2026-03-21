from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational import DjangoAiPromptTestExecutionContext


@dataclass(slots=True, frozen=True)
class PromptTestExecutionContextRecord:
    execution_id: UUID
    test_automation_id: UUID
    test_automation_name: str
    provider_slug: str
    model_slug: str
    created_at: datetime | None
    updated_at: datetime | None


class PromptTestExecutionContextRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        model: DjangoAiPromptTestExecutionContext,
    ) -> DjangoAiPromptTestExecutionContext:
        self.session.add(model)
        self.session.flush()
        return model

    def get_by_execution_id(self, execution_id: UUID) -> PromptTestExecutionContextRecord | None:
        stmt = select(DjangoAiPromptTestExecutionContext).where(
            DjangoAiPromptTestExecutionContext.execution_id == execution_id
        )
        record = self.session.execute(stmt).scalar_one_or_none()
        if record is None:
            return None
        return PromptTestExecutionContextRecord(
            execution_id=record.execution_id,
            test_automation_id=record.test_automation_id,
            test_automation_name=str(record.test_automation_name or "").strip() or str(record.test_automation_id),
            provider_slug=str(record.provider_slug or "").strip().lower(),
            model_slug=str(record.model_slug or "").strip().lower(),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
