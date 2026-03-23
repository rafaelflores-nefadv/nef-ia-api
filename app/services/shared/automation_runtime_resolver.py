from dataclasses import dataclass
import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.repositories.operational import (
    ProviderCredentialRepository,
    ProviderModelRepository,
    ProviderRepository,
)
from app.repositories.shared.automation_repository import SharedAutomationRepository


@dataclass(slots=True)
class AutomationRuntimeResolution:
    automation_id: uuid.UUID
    automation_slug: str | None
    prompt_text: str
    prompt_version: int
    provider_id: uuid.UUID | None
    model_id: uuid.UUID | None
    provider_slug: str
    model_slug: str
    credential_id: uuid.UUID | None
    output_type: str | None
    result_parser: str | None
    result_formatter: str | None
    output_schema: dict[str, object] | str | None
    debug_enabled: bool = False


class AutomationRuntimeResolverService:
    """
    Resolve official runtime configuration from the shared general-system database:
    - official prompt text/version
    - runtime ids selected by business system (provider/model/credential)
    - provider/model runtime references for downstream provider execution
    """

    def __init__(self, shared_session: Session, operational_session: Session | None = None) -> None:
        self.repository = SharedAutomationRepository(shared_session)
        self.providers = ProviderRepository(operational_session) if operational_session is not None else None
        self.models = ProviderModelRepository(operational_session) if operational_session is not None else None
        self.credentials = (
            ProviderCredentialRepository(operational_session)
            if operational_session is not None
            else None
        )

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
            raise AppException(
                "Automation not found in general system.",
                status_code=404,
                code="automation_not_found",
                details={"automation_id": str(automation_uuid)},
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

        provider_reference = self._normalize_text(
            getattr(runtime_record, "provider_slug", None)
            if runtime_record is not None
            else getattr(runtime_target, "provider_slug", None) if runtime_target is not None else None
        )
        model_reference = self._normalize_text(
            getattr(runtime_record, "model_slug", None)
            if runtime_record is not None
            else getattr(runtime_target, "model_slug", None) if runtime_target is not None else None
        )

        provider_id = self._coerce_uuid(
            getattr(runtime_record, "provider_id", None)
            if runtime_record is not None
            else getattr(runtime_target, "provider_id", None) if runtime_target is not None else None
        )
        model_id = self._coerce_uuid(
            getattr(runtime_record, "model_id", None)
            if runtime_record is not None
            else getattr(runtime_target, "model_id", None) if runtime_target is not None else None
        )
        credential_id = self._coerce_uuid(
            getattr(runtime_record, "credential_id", None)
            if runtime_record is not None
            else getattr(runtime_target, "credential_id", None) if runtime_target is not None else None
        )

        missing_fields: list[str] = []
        if provider_id is None and not provider_reference:
            missing_fields.append("provider_id")
        if model_id is None and not model_reference:
            missing_fields.append("model_id")
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

        if self.providers is None or self.models is None:
            provider_runtime_ref = provider_reference or (str(provider_id) if provider_id is not None else "")
            model_runtime_ref = model_reference or (str(model_id) if model_id is not None else "")
            resolved_provider_id = provider_id
            resolved_model_id = model_id
        else:
            provider = self.providers.get_by_id(provider_id) if provider_id is not None else None
            provider_reference_slug = (provider_reference or "").strip().lower()
            if provider is None and provider_reference_slug:
                provider = self.providers.get_by_slug(provider_reference_slug)
            if provider is None:
                raise AppException(
                    "Configured provider does not exist in the operational catalog.",
                    status_code=404,
                    code="provider_not_found",
                    details={
                        "provider_id": str(provider_id) if provider_id is not None else None,
                        "provider_reference": provider_reference,
                        "automation_id": str(automation_uuid),
                    },
                )
            if not provider.is_active:
                raise AppException(
                    "Configured provider is inactive in the operational catalog.",
                    status_code=422,
                    code="provider_inactive",
                    details={"provider_id": str(provider_id), "automation_id": str(automation_uuid)},
                )

            model = self.models.get_by_id(model_id) if model_id is not None else None
            model_reference_slug = (model_reference or "").strip().lower()
            if model is None and model_reference_slug:
                model = self.models.get_by_slug(provider.id, model_reference_slug)
                if model is None:
                    model = self.models.get_by_model_slug(model_reference_slug)
            if model is None:
                raise AppException(
                    "Configured model does not exist in the operational catalog.",
                    status_code=404,
                    code="provider_model_not_found",
                    details={
                        "model_id": str(model_id) if model_id is not None else None,
                        "model_reference": model_reference,
                        "automation_id": str(automation_uuid),
                    },
                )
            if model.provider_id != provider.id:
                raise AppException(
                    "Configured model does not belong to configured provider.",
                    status_code=422,
                    code="provider_model_mismatch",
                    details={
                        "provider_id": str(provider.id),
                        "model_id": str(model.id),
                        "automation_id": str(automation_uuid),
                    },
                )
            if not model.is_active:
                raise AppException(
                    "Configured model is inactive in the operational catalog.",
                    status_code=422,
                    code="provider_model_inactive",
                    details={"model_id": str(model.id), "automation_id": str(automation_uuid)},
                )

            if credential_id is not None and self.credentials is not None:
                credential = self.credentials.get_by_id(credential_id)
                if credential is None:
                    raise AppException(
                        "Configured credential does not exist in the operational catalog.",
                        status_code=404,
                        code="provider_credential_not_found",
                        details={"credential_id": str(credential_id), "automation_id": str(automation_uuid)},
                    )
                if credential.provider_id != provider.id:
                    raise AppException(
                        "Configured credential does not belong to configured provider.",
                        status_code=422,
                        code="provider_credential_mismatch",
                        details={
                            "provider_id": str(provider.id),
                            "credential_id": str(credential.id),
                            "automation_id": str(automation_uuid),
                        },
                    )
                if not credential.is_active:
                    raise AppException(
                        "Configured credential is inactive in the operational catalog.",
                        status_code=422,
                        code="provider_credential_inactive",
                        details={"credential_id": str(credential.id), "automation_id": str(automation_uuid)},
                    )

            provider_runtime_ref = str(getattr(provider, "slug", "") or "").strip() or str(provider.id)
            model_runtime_ref = str(getattr(model, "model_slug", "") or "").strip() or str(model.id)
            resolved_provider_id = provider.id
            resolved_model_id = model.id

        return AutomationRuntimeResolution(
            automation_id=automation_uuid,
            automation_slug=(
                getattr(runtime_record, "automation_slug", None)
                if runtime_record is not None
                else getattr(runtime_target, "automation_slug", None) if runtime_target is not None else None
            ),
            prompt_text=runtime_record.prompt_text if runtime_record is not None else "",
            prompt_version=runtime_record.prompt_version if runtime_record is not None else 0,
            provider_id=resolved_provider_id,
            model_id=resolved_model_id,
            provider_slug=provider_runtime_ref,
            model_slug=model_runtime_ref,
            credential_id=credential_id,
            output_type=(
                getattr(runtime_record, "output_type", None)
                if runtime_record is not None
                else getattr(runtime_target, "output_type", None) if runtime_target is not None else None
            ),
            result_parser=(
                getattr(runtime_record, "result_parser", None)
                if runtime_record is not None
                else getattr(runtime_target, "result_parser", None) if runtime_target is not None else None
            ),
            result_formatter=(
                getattr(runtime_record, "result_formatter", None)
                if runtime_record is not None
                else getattr(runtime_target, "result_formatter", None) if runtime_target is not None else None
            ),
            output_schema=(
                getattr(runtime_record, "output_schema", None)
                if runtime_record is not None
                else getattr(runtime_target, "output_schema", None) if runtime_target is not None else None
            ),
            debug_enabled=bool(
                (
                    getattr(runtime_record, "debug_enabled", None)
                    if runtime_record is not None
                    else getattr(runtime_target, "debug_enabled", None) if runtime_target is not None else None
                )
            ),
        )

    @staticmethod
    def _coerce_uuid(value: object | None) -> uuid.UUID | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except ValueError:
            return None

    @staticmethod
    def _normalize_text(value: object | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None
