from dataclasses import dataclass
import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.repositories.shared.automation_repository import SharedAutomationRepository


@dataclass(slots=True)
class AutomationRuntimeResolution:
    automation_id: uuid.UUID
    prompt_text: str
    prompt_version: int
    provider_slug: str
    model_slug: str


class AutomationRuntimeResolverService:
    """
    Resolve official runtime configuration from the shared general-system database:
    - official prompt text/version
    - provider slug selected by business system
    - model slug selected by business system
    """

    def __init__(self, shared_session: Session) -> None:
        self.repository = SharedAutomationRepository(shared_session)

    def resolve(self, automation_id: str | uuid.UUID) -> AutomationRuntimeResolution:
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

        runtime_record = self.repository.get_runtime_config_for_automation(automation_uuid)
        if runtime_record is None:
            raise AppException(
                "Official prompt not found for automation.",
                status_code=404,
                code="prompt_not_found",
                details={"automation_id": str(automation_uuid)},
            )

        missing_fields: list[str] = []
        if not runtime_record.provider_slug:
            missing_fields.append("provider")
        if not runtime_record.model_slug:
            missing_fields.append("model")
        if missing_fields:
            raise AppException(
                "Automation runtime configuration is incomplete in general system.",
                status_code=422,
                code="automation_runtime_configuration_missing",
                details={
                    "automation_id": str(automation_uuid),
                    "missing_fields": missing_fields,
                },
            )

        return AutomationRuntimeResolution(
            automation_id=runtime_record.automation_id,
            prompt_text=runtime_record.prompt_text,
            prompt_version=runtime_record.prompt_version,
            provider_slug=runtime_record.provider_slug,
            model_slug=runtime_record.model_slug,
        )
