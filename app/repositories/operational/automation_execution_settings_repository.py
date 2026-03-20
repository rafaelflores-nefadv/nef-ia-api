import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational import DjangoAiAutomationExecutionSetting


class AutomationExecutionSettingsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item: DjangoAiAutomationExecutionSetting) -> DjangoAiAutomationExecutionSetting:
        self.session.add(item)
        self.session.flush()
        return item

    def list_all(self) -> list[DjangoAiAutomationExecutionSetting]:
        stmt = select(DjangoAiAutomationExecutionSetting).order_by(
            DjangoAiAutomationExecutionSetting.updated_at.desc(),
            DjangoAiAutomationExecutionSetting.created_at.desc(),
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_by_automation_id(self, automation_id: uuid.UUID) -> DjangoAiAutomationExecutionSetting | None:
        stmt = select(DjangoAiAutomationExecutionSetting).where(
            DjangoAiAutomationExecutionSetting.automation_id == automation_id
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_active_by_automation_id(self, automation_id: uuid.UUID) -> DjangoAiAutomationExecutionSetting | None:
        stmt = select(DjangoAiAutomationExecutionSetting).where(
            DjangoAiAutomationExecutionSetting.automation_id == automation_id,
            DjangoAiAutomationExecutionSetting.is_active.is_(True),
        )
        return self.session.execute(stmt).scalar_one_or_none()
