from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.constants import ExecutionStatus
from app.models.operational import DjangoAiApiToken, DjangoAiApiTokenPermission
from app.repositories.operational import (
    ApiTokenRepository,
    ProviderCredentialRepository,
    ProviderModelRepository,
    ProviderRepository,
    QueueJobRepository,
)
from app.repositories.shared import SharedAnalysisRepository, SharedAutomationRepository
from app.services.execution_service import ExecutionService
from app.services.execution_engine import ExecutionFormatterStrategy, ExecutionOutputType, ExecutionParserStrategy
from app.services.file_service import DownloadableFile, FileService


@dataclass(slots=True, frozen=True)
class AdminAutomationExecutionStartResult:
    automation_id: UUID
    analysis_request_id: UUID
    request_file_id: UUID
    execution_id: UUID
    queue_job_id: UUID
    status: ExecutionStatus
    prompt_version: int
    prompt_override_applied: bool


class AdminAutomationExecutionService:
    OUTPUT_TYPE_ALIASES = {
        "text": ExecutionOutputType.TEXT_OUTPUT.value,
        "text_raw": ExecutionOutputType.TEXT_OUTPUT.value,
        "plain_text": ExecutionOutputType.TEXT_OUTPUT.value,
        "text_output": ExecutionOutputType.TEXT_OUTPUT.value,
        "spreadsheet": ExecutionOutputType.SPREADSHEET_OUTPUT.value,
        "spreadsheet_output": ExecutionOutputType.SPREADSHEET_OUTPUT.value,
        "xlsx": ExecutionOutputType.SPREADSHEET_OUTPUT.value,
        "excel": ExecutionOutputType.SPREADSHEET_OUTPUT.value,
    }
    RESULT_PARSER_ALIASES = {
        "text": ExecutionParserStrategy.TEXT_RAW.value,
        "raw": ExecutionParserStrategy.TEXT_RAW.value,
        "text_raw": ExecutionParserStrategy.TEXT_RAW.value,
        "structured": ExecutionParserStrategy.TABULAR_STRUCTURED.value,
        "structured_tabular": ExecutionParserStrategy.TABULAR_STRUCTURED.value,
        "tabular_structured": ExecutionParserStrategy.TABULAR_STRUCTURED.value,
    }
    RESULT_FORMATTER_ALIASES = {
        "text": ExecutionFormatterStrategy.TEXT_PLAIN.value,
        "plain_text": ExecutionFormatterStrategy.TEXT_PLAIN.value,
        "text_plain": ExecutionFormatterStrategy.TEXT_PLAIN.value,
        "spreadsheet": ExecutionFormatterStrategy.SPREADSHEET_TABULAR.value,
        "spreadsheet_tabular": ExecutionFormatterStrategy.SPREADSHEET_TABULAR.value,
        "tabular_spreadsheet": ExecutionFormatterStrategy.SPREADSHEET_TABULAR.value,
    }

    def __init__(
        self,
        *,
        operational_session: Session,
        shared_session: Session,
    ) -> None:
        self.operational_session = operational_session
        self.shared_session = shared_session
        self.shared_automations = SharedAutomationRepository(shared_session)
        self.shared_analysis = SharedAnalysisRepository(shared_session)
        self.api_tokens = ApiTokenRepository(operational_session)
        self.providers = ProviderRepository(operational_session)
        self.provider_models = ProviderModelRepository(operational_session)
        self.provider_credentials = ProviderCredentialRepository(operational_session)
        self.queue_jobs = QueueJobRepository(operational_session)
        self.file_service = FileService(
            operational_session=operational_session,
            shared_session=shared_session,
        )
        self.execution_service = ExecutionService(
            operational_session=operational_session,
            shared_session=shared_session,
        )

    @staticmethod
    def _coerce_uuid(value: object | None) -> UUID | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return UUID(raw)
        except ValueError:
            return None

    @staticmethod
    def _normalize_runtime_schema(value: object | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        raw = str(value).strip()
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise AppException(
                "Output schema is invalid: expected a JSON object.",
                status_code=422,
                code="execution_output_schema_invalid",
            )
        if not isinstance(payload, dict):
            raise AppException(
                "Output schema is invalid: expected a JSON object.",
                status_code=422,
                code="execution_output_schema_invalid",
            )
        return payload

    @classmethod
    def _normalize_output_type(cls, value: object | None, *, default_if_none: bool) -> str | None:
        if value is None:
            return ExecutionOutputType.TEXT_OUTPUT.value if default_if_none else None
        normalized = str(value).strip().lower()
        if not normalized:
            if default_if_none:
                return ExecutionOutputType.TEXT_OUTPUT.value
            return None
        resolved = cls.OUTPUT_TYPE_ALIASES.get(normalized, normalized)
        try:
            return ExecutionOutputType(resolved).value
        except ValueError as exc:
            raise AppException(
                "Output contract is invalid: unsupported output_type.",
                status_code=422,
                code="execution_output_contract_invalid",
                details={"output_type": value},
            ) from exc

    @classmethod
    def _normalize_result_parser(cls, value: object | None, *, default_if_none: bool) -> str | None:
        if value is None:
            return ExecutionParserStrategy.TEXT_RAW.value if default_if_none else None
        normalized = str(value).strip().lower()
        if not normalized:
            if default_if_none:
                return ExecutionParserStrategy.TEXT_RAW.value
            return None
        resolved = cls.RESULT_PARSER_ALIASES.get(normalized, normalized)
        try:
            return ExecutionParserStrategy(resolved).value
        except ValueError as exc:
            raise AppException(
                "Output contract is invalid: unsupported result_parser.",
                status_code=422,
                code="execution_output_contract_invalid",
                details={"result_parser": value},
            ) from exc

    @classmethod
    def _normalize_result_formatter(cls, value: object | None, *, default_if_none: bool) -> str | None:
        if value is None:
            return ExecutionFormatterStrategy.TEXT_PLAIN.value if default_if_none else None
        normalized = str(value).strip().lower()
        if not normalized:
            if default_if_none:
                return ExecutionFormatterStrategy.TEXT_PLAIN.value
            return None
        resolved = cls.RESULT_FORMATTER_ALIASES.get(normalized, normalized)
        try:
            return ExecutionFormatterStrategy(resolved).value
        except ValueError as exc:
            raise AppException(
                "Output contract is invalid: unsupported result_formatter.",
                status_code=422,
                code="execution_output_contract_invalid",
                details={"result_formatter": value},
            ) from exc

    def _validate_catalog_references(
        self,
        *,
        provider_id: UUID,
        model_id: UUID,
        credential_id: UUID | None,
    ) -> tuple[str | None, str | None, str | None]:
        provider = self.providers.get_by_id(provider_id)
        if provider is None:
            raise AppException(
                "Provider not found in operational catalog.",
                status_code=404,
                code="provider_not_found",
                details={"provider_id": str(provider_id)},
            )
        if not provider.is_active:
            raise AppException(
                "Configured provider is inactive in the operational catalog.",
                status_code=422,
                code="provider_inactive",
                details={"provider_id": str(provider_id)},
            )

        model = self.provider_models.get_by_id(model_id)
        if model is None:
            raise AppException(
                "Model not found in operational catalog.",
                status_code=404,
                code="provider_model_not_found",
                details={"model_id": str(model_id)},
            )
        if model.provider_id != provider_id:
            raise AppException(
                "Configured model does not belong to configured provider.",
                status_code=422,
                code="provider_model_mismatch",
                details={"provider_id": str(provider_id), "model_id": str(model_id)},
            )
        if not model.is_active:
            raise AppException(
                "Configured model is inactive in the operational catalog.",
                status_code=422,
                code="provider_model_inactive",
                details={"provider_id": str(provider_id), "model_id": str(model_id)},
            )

        credential_name: str | None = None
        if credential_id is not None:
            credential = self.provider_credentials.get_by_id(credential_id)
            if credential is None:
                raise AppException(
                    "Credential not found in operational catalog.",
                    status_code=404,
                    code="provider_credential_not_found",
                    details={"credential_id": str(credential_id)},
                )
            if credential.provider_id != provider_id:
                raise AppException(
                    "Configured credential does not belong to configured provider.",
                    status_code=422,
                    code="provider_credential_mismatch",
                    details={"provider_id": str(provider_id), "credential_id": str(credential_id)},
                )
            if not credential.is_active:
                raise AppException(
                    "Configured credential is inactive in the operational catalog.",
                    status_code=422,
                    code="provider_credential_inactive",
                    details={"provider_id": str(provider_id), "credential_id": str(credential_id)},
                )
            credential_name = str(credential.credential_name or "").strip() or str(credential.id)

        provider_slug = str(provider.slug or "").strip().lower() or None
        model_slug = str(model.model_slug or "").strip().lower() or None
        return provider_slug, model_slug, credential_name

    def _compose_runtime_payload(
        self,
        *,
        automation,
        runtime,
        runtime_target,
        latest_request,
        owner_token_name: str | None,
    ) -> dict[str, Any]:
        prompt_text = runtime.prompt_text if runtime is not None else ""
        resolved_slug = (
            runtime.automation_slug
            if runtime is not None and runtime.automation_slug is not None
            else runtime_target.automation_slug if runtime_target is not None else None
        )
        provider_id = (
            runtime.provider_id
            if runtime is not None and runtime.provider_id is not None
            else runtime_target.provider_id if runtime_target is not None else None
        )
        model_id = (
            runtime.model_id
            if runtime is not None and runtime.model_id is not None
            else runtime_target.model_id if runtime_target is not None else None
        )
        credential_id = (
            self._coerce_uuid(runtime.credential_id) if runtime is not None else None
        ) or (
            self._coerce_uuid(runtime_target.credential_id) if runtime_target is not None else None
        )

        provider_slug = (
            runtime.provider_slug
            if runtime is not None and runtime.provider_slug is not None
            else runtime_target.provider_slug if runtime_target is not None else None
        )
        model_slug = (
            runtime.model_slug
            if runtime is not None and runtime.model_slug is not None
            else runtime_target.model_slug if runtime_target is not None else None
        )
        credential_name = runtime.credential_name if runtime is not None else None

        if provider_id is not None:
            provider = self.providers.get_by_id(provider_id)
            if provider is not None:
                provider_slug = str(provider.slug or "").strip().lower() or provider_slug
        if model_id is not None:
            model = self.provider_models.get_by_id(model_id)
            if model is not None:
                model_slug = str(model.model_slug or "").strip().lower() or model_slug
        if credential_id is not None and not credential_name:
            credential = self.provider_credentials.get_by_id(credential_id)
            if credential is not None:
                credential_name = str(credential.credential_name or "").strip() or None

        output_type = (
            runtime.output_type
            if runtime is not None and runtime.output_type is not None
            else runtime_target.output_type if runtime_target is not None else None
        )
        result_parser = (
            runtime.result_parser
            if runtime is not None and runtime.result_parser is not None
            else runtime_target.result_parser if runtime_target is not None else None
        )
        result_formatter = (
            runtime.result_formatter
            if runtime is not None and runtime.result_formatter is not None
            else runtime_target.result_formatter if runtime_target is not None else None
        )
        output_schema = (
            runtime.output_schema
            if runtime is not None and runtime.output_schema is not None
            else runtime_target.output_schema if runtime_target is not None else None
        )
        debug_enabled = (
            runtime.debug_enabled
            if runtime is not None and runtime.debug_enabled is not None
            else runtime_target.debug_enabled if runtime_target is not None else None
        )

        return {
            "automation_id": automation.id,
            "automation_name": str(automation.name or "").strip() or str(automation.id),
            "automation_slug": resolved_slug,
            "automation_is_active": bool(automation.is_active),
            "owner_token_name": owner_token_name,
            "prompt_available": runtime is not None,
            "prompt_id": runtime.prompt_id if runtime is not None else None,
            "prompt_is_active": runtime.prompt_is_active if runtime is not None else None,
            "prompt_version": runtime.prompt_version if runtime is not None else None,
            "prompt_summary": self._summarize_prompt_text(prompt_text),
            "prompt_text": prompt_text,
            "provider_id": provider_id,
            "model_id": model_id,
            "credential_id": credential_id,
            "credential_name": credential_name,
            "provider_slug": provider_slug,
            "model_slug": model_slug,
            "output_type": output_type,
            "result_parser": result_parser,
            "result_formatter": result_formatter,
            "output_schema": output_schema,
            "debug_enabled": debug_enabled,
            "latest_analysis_request_id": latest_request.id if latest_request is not None else None,
            "is_test_automation": False,
        }

    @staticmethod
    def _normalize_token_name(value: object | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    def _resolve_owner_token_name(self, *, owner_token_id: UUID | None) -> str | None:
        if owner_token_id is None:
            return None
        token = self.api_tokens.get_by_id(owner_token_id)
        if token is None:
            return "Chave nao encontrada"
        return self._normalize_token_name(getattr(token, "name", None)) or "Chave sem nome"

    def _resolve_owner_token_name_map(self, *, owner_token_ids: set[UUID]) -> dict[UUID, str]:
        if not owner_token_ids:
            return {}
        token_id_set = set(owner_token_ids)
        names: dict[UUID, str] = {}
        for token in self.api_tokens.list_all():
            token_id = getattr(token, "id", None)
            if token_id not in token_id_set:
                continue
            normalized = self._normalize_token_name(getattr(token, "name", None))
            if normalized:
                names[token_id] = normalized
        return names

    @staticmethod
    def _summarize_prompt_text(prompt_text: str, *, limit: int = 220) -> str:
        normalized = " ".join(str(prompt_text or "").split()).strip()
        if not normalized:
            return ""
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit].rstrip()}..."

    def list_automation_runtimes(self) -> list[dict[str, Any]]:
        automations = self.shared_automations.list_automations()
        owner_token_ids = {
            automation.owner_token_id
            for automation in automations
            if automation.owner_token_id is not None
        }
        owner_token_names = self._resolve_owner_token_name_map(owner_token_ids=owner_token_ids)
        items: list[dict[str, Any]] = []
        for automation in automations:
            runtime = self.shared_automations.get_runtime_config_for_automation(automation.id)
            runtime_target = self.shared_automations.get_runtime_target_for_automation(automation.id)
            latest_request = self.shared_analysis.get_latest_request_by_automation_id(automation.id)
            owner_token_name = (
                owner_token_names.get(automation.owner_token_id)
                if automation.owner_token_id
                else None
            )
            if automation.owner_token_id is not None and not owner_token_name:
                owner_token_name = "Chave nao encontrada"
            items.append(
                self._compose_runtime_payload(
                    automation=automation,
                    runtime=runtime,
                    runtime_target=runtime_target,
                    latest_request=latest_request,
                    owner_token_name=owner_token_name,
                )
            )
        return items

    def get_automation_runtime(self, *, automation_id: UUID) -> dict[str, Any]:
        automation = self.shared_automations.get_automation_by_id(automation_id)
        if automation is None:
            raise AppException(
                "Automation not found.",
                status_code=404,
                code="automation_not_found",
                details={"automation_id": str(automation_id)},
            )
        runtime = self.shared_automations.get_runtime_config_for_automation(automation_id)
        runtime_target = self.shared_automations.get_runtime_target_for_automation(automation_id)
        latest_request = self.shared_analysis.get_latest_request_by_automation_id(automation_id)
        owner_token_name = self._resolve_owner_token_name(owner_token_id=automation.owner_token_id)
        return self._compose_runtime_payload(
            automation=automation,
            runtime=runtime,
            runtime_target=runtime_target,
            latest_request=latest_request,
            owner_token_name=owner_token_name,
        )

    def update_automation_runtime(self, *, automation_id: UUID, changes: dict[str, Any]) -> dict[str, Any]:
        automation = self.shared_automations.get_automation_by_id(automation_id)
        if automation is None:
            raise AppException(
                "Automation not found.",
                status_code=404,
                code="automation_not_found",
                details={"automation_id": str(automation_id)},
            )

        normalized_changes = dict(changes or {})
        automation_changes: dict[str, object] = {}

        if "name" in normalized_changes:
            normalized_name = str(normalized_changes.get("name") or "").strip()
            if not normalized_name:
                raise AppException(
                    "Automation name cannot be empty.",
                    status_code=422,
                    code="validation_error",
                    details={"field": "name"},
                )
            automation_changes["name"] = normalized_name

        runtime_target = self.shared_automations.get_runtime_target_for_automation(automation_id)
        current_provider_id = runtime_target.provider_id if runtime_target is not None else None
        current_model_id = runtime_target.model_id if runtime_target is not None else None
        current_credential_id = self._coerce_uuid(runtime_target.credential_id) if runtime_target is not None else None

        provider_id = current_provider_id
        if "provider_id" in normalized_changes:
            provider_id = self._coerce_uuid(normalized_changes.get("provider_id"))
            if provider_id is None:
                raise AppException(
                    "Provider is required.",
                    status_code=422,
                    code="provider_not_found",
                )
            automation_changes["provider_id"] = provider_id

        model_id = current_model_id
        if "model_id" in normalized_changes:
            model_id = self._coerce_uuid(normalized_changes.get("model_id"))
            if model_id is None:
                raise AppException(
                    "Model is required.",
                    status_code=422,
                    code="provider_model_not_found",
                )
            automation_changes["model_id"] = model_id

        credential_id = current_credential_id
        if "credential_id" in normalized_changes:
            credential_id = self._coerce_uuid(normalized_changes.get("credential_id"))
            automation_changes["credential_id"] = credential_id

        if "output_type" in normalized_changes:
            automation_changes["output_type"] = self._normalize_output_type(
                normalized_changes.get("output_type"),
                default_if_none=False,
            )
        if "result_parser" in normalized_changes:
            automation_changes["result_parser"] = self._normalize_result_parser(
                normalized_changes.get("result_parser"),
                default_if_none=False,
            )
        if "result_formatter" in normalized_changes:
            automation_changes["result_formatter"] = self._normalize_result_formatter(
                normalized_changes.get("result_formatter"),
                default_if_none=False,
            )
        if "output_schema" in normalized_changes:
            automation_changes["output_schema"] = self._normalize_runtime_schema(normalized_changes.get("output_schema"))

        runtime_fields_requested = any(
            key in normalized_changes
            for key in (
                "provider_id",
                "model_id",
                "credential_id",
                "output_type",
                "result_parser",
                "result_formatter",
                "output_schema",
            )
        )
        if runtime_fields_requested:
            if provider_id is None or model_id is None:
                raise AppException(
                    "Automation runtime configuration requires provider and model.",
                    status_code=422,
                    code="automation_runtime_configuration_missing",
                    details={"automation_id": str(automation_id), "missing_fields": ["provider", "model"]},
                )
            self._validate_catalog_references(
                provider_id=provider_id,
                model_id=model_id,
                credential_id=credential_id,
            )

        prompt_text_to_upsert: str | None = None
        if "prompt_text" in normalized_changes:
            prompt_text_to_upsert = str(normalized_changes.get("prompt_text") or "").strip()
            if not prompt_text_to_upsert:
                raise AppException(
                    "Prompt text cannot be empty.",
                    status_code=422,
                    code="invalid_prompt_override",
                    details={"automation_id": str(automation_id)},
                )

        if not automation_changes and prompt_text_to_upsert is None:
            return self.get_automation_runtime(automation_id=automation_id)

        try:
            if automation_changes:
                updated = self.shared_automations.update_automation_fields(
                    automation_id=automation_id,
                    changes=automation_changes,
                )
                if not updated:
                    raise AppException(
                        "Automation not found.",
                        status_code=404,
                        code="automation_not_found",
                        details={"automation_id": str(automation_id)},
                    )

            if prompt_text_to_upsert is not None:
                self.shared_automations.upsert_latest_prompt_for_automation(
                    automation_id=automation_id,
                    prompt_text=prompt_text_to_upsert,
                    is_active=True,
                )

            self.shared_session.commit()
        except AppException:
            self.shared_session.rollback()
            raise
        except Exception:
            self.shared_session.rollback()
            raise

        return self.get_automation_runtime(automation_id=automation_id)

    def set_automation_runtime_status(self, *, automation_id: UUID, is_active: bool) -> dict[str, Any]:
        automation = self.shared_automations.get_automation_by_id(automation_id)
        if automation is None:
            raise AppException(
                "Automation not found.",
                status_code=404,
                code="automation_not_found",
                details={"automation_id": str(automation_id)},
            )
        try:
            updated = self.shared_automations.set_automation_status(
                automation_id=automation_id,
                is_active=bool(is_active),
            )
            if not updated:
                raise AppException(
                    "Automation not found.",
                    status_code=404,
                    code="automation_not_found",
                    details={"automation_id": str(automation_id)},
                )
            self.shared_session.commit()
        except AppException:
            self.shared_session.rollback()
            raise
        except Exception:
            self.shared_session.rollback()
            raise
        return self.get_automation_runtime(automation_id=automation_id)

    def delete_automation_runtime(self, *, automation_id: UUID) -> None:
        automation = self.shared_automations.get_automation_by_id(automation_id)
        if automation is None:
            raise AppException(
                "Automation not found.",
                status_code=404,
                code="automation_not_found",
                details={"automation_id": str(automation_id)},
            )
        try:
            self.shared_automations.delete_prompts_for_automation(automation_id=automation_id)
            deleted = self.shared_automations.delete_automation_by_id(automation_id=automation_id)
            if not deleted:
                raise AppException(
                    "Automation not found.",
                    status_code=404,
                    code="automation_not_found",
                    details={"automation_id": str(automation_id)},
                )
            self.shared_session.commit()
        except AppException:
            self.shared_session.rollback()
            raise
        except IntegrityError as exc:
            self.shared_session.rollback()
            raise AppException(
                "Deletion blocked by existing dependencies.",
                status_code=409,
                code="delete_blocked_by_dependencies",
                details={"automation_id": str(automation_id), "reason": str(exc.orig) if exc.orig else str(exc)},
            ) from exc
        except Exception:
            self.shared_session.rollback()
            raise

    def list_active_provider_models(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for provider in self.providers.list_active():
            models = self.provider_models.list_by_provider(provider.id)
            for model in models:
                if not model.is_active:
                    continue
                items.append(
                    {
                        "provider_id": provider.id,
                        "provider_name": str(provider.name or "").strip() or str(provider.id),
                        "provider_slug": str(provider.slug or "").strip().lower(),
                        "model_id": model.id,
                        "model_name": str(model.model_name or "").strip() or str(model.id),
                        "model_slug": str(model.model_slug or "").strip().lower(),
                    }
                )
        return sorted(
            items,
            key=lambda item: (
                str(item["provider_name"]).lower(),
                str(item["model_name"]).lower(),
            ),
        )

    @staticmethod
    def _build_admin_token_and_permissions(
        *,
        actor_user_id: UUID,
        automation_id: UUID,
    ) -> tuple[DjangoAiApiToken, list[DjangoAiApiTokenPermission]]:
        token = DjangoAiApiToken(
            id=uuid.uuid4(),
            name="admin-panel-runtime",
            token_hash="admin-panel-runtime",
            is_active=True,
            expires_at=None,
            created_by_user_id=actor_user_id,
        )
        permissions = [
            DjangoAiApiTokenPermission(
                token_id=token.id,
                automation_id=automation_id,
                provider_id=None,
                allow_execution=True,
                allow_file_upload=True,
            )
        ]
        return token, permissions

    def start_execution_for_automation(
        self,
        *,
        automation_id: UUID,
        upload_file: UploadFile,
        prompt_override: str | None,
        actor_user_id: UUID,
        ip_address: str | None,
        correlation_id: str | None = None,
    ) -> AdminAutomationExecutionStartResult:
        automation = self.shared_automations.get_automation_by_id(automation_id)
        if automation is None:
            raise AppException(
                "Automation not found.",
                status_code=404,
                code="automation_not_found",
                details={"automation_id": str(automation_id)},
            )

        normalized_prompt_override = str(prompt_override or "").strip() or None
        runtime = self.shared_automations.get_runtime_config_for_automation(automation_id) if automation is not None else None
        if runtime is None and not normalized_prompt_override:
            raise AppException(
                "Prompt not found for execution and no prompt_override was provided.",
                status_code=404,
                code="prompt_not_found",
                details={"automation_id": str(automation_id)},
            )

        latest_request = self.shared_analysis.get_latest_request_by_automation_id(automation_id)
        permission_automation_id = automation_id
        if latest_request is None:
            raise AppException(
                "No analysis_request available for selected automation.",
                status_code=422,
                code="analysis_request_not_found_for_automation",
                details={"automation_id": str(automation_id)},
            )

        admin_token, permissions = self._build_admin_token_and_permissions(
            actor_user_id=actor_user_id,
            automation_id=permission_automation_id,
        )

        request_file = self.file_service.upload_request_file(
            analysis_request_id=latest_request.id,
            upload_file=upload_file,
            api_token=admin_token,
            token_permissions=permissions,
            ip_address=ip_address,
        )
        execution = self.execution_service.create_execution(
            analysis_request_id=latest_request.id,
            request_file_id=request_file.id,
            prompt_override=normalized_prompt_override,
            api_token=admin_token,
            token_permissions=permissions,
            ip_address=ip_address,
            correlation_id=correlation_id,
        )
        return AdminAutomationExecutionStartResult(
            automation_id=automation_id,
            analysis_request_id=latest_request.id,
            request_file_id=request_file.id,
            execution_id=execution.execution_id,
            queue_job_id=execution.queue_job_id,
            status=execution.status,
            prompt_version=runtime.prompt_version if runtime is not None else 0,
            prompt_override_applied=bool(normalized_prompt_override),
        )

    def get_execution_status_for_admin(self, *, execution_id: UUID, actor_user_id: UUID) -> dict[str, Any]:
        shared_execution = self.shared_analysis.get_execution_by_id(execution_id)
        if shared_execution is None:
            raise AppException(
                "Execution not found.",
                status_code=404,
                code="execution_not_found",
                details={"execution_id": str(execution_id)},
            )
        shared_request = self.shared_analysis.get_request_by_id(shared_execution.analysis_request_id)
        if shared_request is None:
            raise AppException(
                "Related analysis request not found.",
                status_code=404,
                code="analysis_request_not_found",
                details={"analysis_request_id": str(shared_execution.analysis_request_id)},
            )

        _, permissions = self._build_admin_token_and_permissions(
            actor_user_id=actor_user_id,
            automation_id=shared_request.automation_id,
        )
        result = self.execution_service.get_execution_status(
            execution_id=execution_id,
            token_permissions=permissions,
        )
        request_file_id: UUID | None = None
        request_file_name: str | None = None
        prompt_override_applied = False
        latest_queue_job = self.queue_jobs.get_latest_by_execution_id(execution_id)
        if latest_queue_job is not None:
            prompt_override_applied = bool(str(latest_queue_job.prompt_override_text or "").strip())
            if latest_queue_job.request_file_id is not None:
                request_file = self.file_service.request_files.get_by_id(latest_queue_job.request_file_id)
                request_file_id = latest_queue_job.request_file_id
                if request_file is not None:
                    request_file_name = request_file.file_name

        return {
            "execution_id": result.execution_id,
            "analysis_request_id": shared_execution.analysis_request_id,
            "automation_id": shared_request.automation_id,
            "request_file_id": request_file_id,
            "request_file_name": request_file_name,
            "prompt_override_applied": prompt_override_applied,
            "status": result.status,
            "progress": result.progress,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "error_message": result.error_message,
            "created_at": result.created_at,
            "checked_at": datetime.now(timezone.utc),
        }

    def get_execution_file_for_admin_download(
        self,
        *,
        file_id: UUID,
        actor_user_id: UUID,
    ) -> DownloadableFile:
        execution_file = self.file_service.execution_files.get_by_id(file_id)
        if execution_file is None:
            raise AppException(
                "Execution file not found.",
                status_code=404,
                code="execution_file_not_found",
                details={"file_id": str(file_id)},
            )

        shared_execution = self.shared_analysis.get_execution_by_id(execution_file.execution_id)
        if shared_execution is None:
            raise AppException(
                "Related execution not found.",
                status_code=404,
                code="analysis_execution_not_found",
                details={"execution_id": str(execution_file.execution_id)},
            )
        shared_request = self.shared_analysis.get_request_by_id(shared_execution.analysis_request_id)
        if shared_request is None:
            raise AppException(
                "Related analysis request not found.",
                status_code=404,
                code="analysis_request_not_found",
                details={"analysis_request_id": str(shared_execution.analysis_request_id)},
            )

        _, permissions = self._build_admin_token_and_permissions(
            actor_user_id=actor_user_id,
            automation_id=shared_request.automation_id,
        )
        return self.file_service.get_execution_file_for_download(
            file_id=file_id,
            token_permissions=permissions,
        )
