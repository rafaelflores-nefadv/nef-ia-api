from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational.system_explanation_prompt import DjangoAiSystemExplanationPrompt


class SystemExplanationPromptRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_active_prompt(self) -> str | None:
        stmt = (
            select(DjangoAiSystemExplanationPrompt)
            .where(DjangoAiSystemExplanationPrompt.is_active.is_(True))
            .limit(1)
        )
        item = self.session.execute(stmt).scalar_one_or_none()
        return item.prompt_text if item is not None else None
