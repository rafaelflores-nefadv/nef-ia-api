from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational import DjangoAiExternalExecutionContext


@dataclass(slots=True)
class ExternalExecutionContextRecord:
    id: UUID
    execution_id: UUID
    token_id: UUID
    analysis_request_id: UUID
    resource_type: str
    automation_id: UUID
    prompt_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ExternalExecutionContextRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item: DjangoAiExternalExecutionContext) -> DjangoAiExternalExecutionContext:
        self.session.add(item)
        self.session.flush()
        return item

    def create(
        self,
        *,
        execution_id: UUID,
        token_id: UUID,
        analysis_request_id: UUID,
        resource_type: str,
        automation_id: UUID,
        prompt_id: UUID | None = None,
    ) -> ExternalExecutionContextRecord:
        model = DjangoAiExternalExecutionContext(
            id=uuid.uuid4(),
            execution_id=execution_id,
            token_id=token_id,
            analysis_request_id=analysis_request_id,
            resource_type=str(resource_type).strip().lower(),
            automation_id=automation_id,
            prompt_id=prompt_id,
        )
        self.add(model)
        return self._to_record(model)

    def get_by_execution_id_and_scope(
        self,
        *,
        execution_id: UUID,
        token_id: UUID,
        resource_type: str | None = None,
    ) -> ExternalExecutionContextRecord | None:
        stmt = select(DjangoAiExternalExecutionContext).where(
            DjangoAiExternalExecutionContext.execution_id == execution_id,
            DjangoAiExternalExecutionContext.token_id == token_id,
        )
        if resource_type is not None:
            stmt = stmt.where(DjangoAiExternalExecutionContext.resource_type == str(resource_type).strip().lower())
        model = self.session.execute(stmt).scalar_one_or_none()
        if model is None:
            return None
        return self._to_record(model)

    def list_by_scope(
        self,
        *,
        token_id: UUID,
        resource_type: str | None = None,
        automation_id: UUID | None = None,
        prompt_id: UUID | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[ExternalExecutionContextRecord]:
        stmt = select(DjangoAiExternalExecutionContext).where(DjangoAiExternalExecutionContext.token_id == token_id)
        if resource_type is not None:
            stmt = stmt.where(DjangoAiExternalExecutionContext.resource_type == str(resource_type).strip().lower())
        if automation_id is not None:
            stmt = stmt.where(DjangoAiExternalExecutionContext.automation_id == automation_id)
        if prompt_id is not None:
            stmt = stmt.where(DjangoAiExternalExecutionContext.prompt_id == prompt_id)
        stmt = stmt.order_by(
            DjangoAiExternalExecutionContext.created_at.desc(),
            DjangoAiExternalExecutionContext.id.desc(),
        )
        if offset is not None and int(offset) > 0:
            stmt = stmt.offset(int(offset))
        if limit is not None:
            stmt = stmt.limit(max(int(limit), 0))
        models = list(self.session.execute(stmt).scalars().all())
        return [self._to_record(item) for item in models]

    @staticmethod
    def _to_record(item: DjangoAiExternalExecutionContext) -> ExternalExecutionContextRecord:
        return ExternalExecutionContextRecord(
            id=item.id,
            execution_id=item.execution_id,
            token_id=item.token_id,
            analysis_request_id=item.analysis_request_id,
            resource_type=item.resource_type,
            automation_id=item.automation_id,
            prompt_id=item.prompt_id,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
