from dataclasses import dataclass
import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.repositories.shared.automation_repository import SharedAutomationRepository


@dataclass(slots=True)
class PromptResolution:
    automation_id: uuid.UUID
    prompt_text: str
    prompt_version: int


class PromptResolverService:
    """
    Etapa 1 contract:
    - API receives an automation identifier.
    - API queries general-system tables in shared PostgreSQL.
    - API resolves official prompt from automation_prompts.
    """

    def __init__(self, shared_session: Session) -> None:
        self.repository = SharedAutomationRepository(shared_session)

    def resolve_official_prompt(self, automation_id: str | uuid.UUID) -> PromptResolution:
        try:
            automation_uuid = uuid.UUID(str(automation_id))
        except ValueError as exc:
            raise AppException(
                "Invalid automation identifier format.",
                status_code=422,
                code="invalid_automation_id",
                details={"automation_id": str(automation_id)},
            ) from exc
        automation = self.repository.get_automation_by_id(automation_uuid)
        if automation is None:
            raise AppException(
                "Automation not found in general system.",
                status_code=404,
                code="automation_not_found",
                details={"automation_id": str(automation_uuid)},
            )

        prompt = self.repository.get_latest_prompt_for_automation(automation_uuid)
        if prompt is None:
            raise AppException(
                "Official prompt not found for automation.",
                status_code=404,
                code="prompt_not_found",
                details={"automation_id": str(automation_uuid)},
            )

        return PromptResolution(
            automation_id=automation_uuid,
            prompt_text=prompt.prompt_text,
            prompt_version=prompt.version,
        )
