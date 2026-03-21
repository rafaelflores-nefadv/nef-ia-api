from dataclasses import dataclass
import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.repositories.prompt_tests import PromptTestAutomationRepository
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
        self.test_automations = PromptTestAutomationRepository(shared_session)

    def resolve(
        self,
        automation_id: str | uuid.UUID,
        *,
        require_prompt: bool = True,
    ) -> AutomationRuntimeResolution:
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
            try:
                test_automation = self.test_automations.get_by_id(automation_uuid)
            except Exception:
                test_automation = None
            if test_automation is None:
                raise AppException(
                    "Automation not found in general system.",
                    status_code=404,
                    code="automation_not_found",
                    details={"automation_id": str(automation_uuid)},
                )

            provider_slug = str(test_automation.provider_slug or "").strip().lower()
            model_slug = str(test_automation.model_slug or "").strip().lower()
            missing_fields: list[str] = []
            if not provider_slug:
                missing_fields.append("provider")
            if not model_slug:
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
            if require_prompt:
                raise AppException(
                    "Official prompt not found for automation.",
                    status_code=404,
                    code="prompt_not_found",
                    details={"automation_id": str(automation_uuid)},
                )
            return AutomationRuntimeResolution(
                automation_id=automation_uuid,
                prompt_text="",
                prompt_version=0,
                provider_slug=provider_slug,
                model_slug=model_slug,
            )

        runtime_record = self.repository.get_runtime_config_for_automation(automation_uuid)
        if runtime_record is None and require_prompt:
            raise AppException(
                "Official prompt not found for automation.",
                status_code=404,
                code="prompt_not_found",
                details={"automation_id": str(automation_uuid)},
            )

        runtime_target = None
        if runtime_record is None:
            runtime_target = self.repository.get_runtime_target_for_automation(automation_uuid)
            if runtime_target is None:
                raise AppException(
                    "Automation not found in general system.",
                    status_code=404,
                    code="automation_not_found",
                    details={"automation_id": str(automation_uuid)},
                )

        missing_fields: list[str] = []
        provider_slug = (
            runtime_record.provider_slug
            if runtime_record is not None
            else runtime_target.provider_slug if runtime_target is not None else None
        )
        model_slug = (
            runtime_record.model_slug
            if runtime_record is not None
            else runtime_target.model_slug if runtime_target is not None else None
        )
        if not provider_slug:
            missing_fields.append("provider")
        if not model_slug:
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
            automation_id=automation_uuid,
            prompt_text=runtime_record.prompt_text if runtime_record is not None else "",
            prompt_version=runtime_record.prompt_version if runtime_record is not None else 0,
            provider_slug=provider_slug,
            model_slug=model_slug,
        )
