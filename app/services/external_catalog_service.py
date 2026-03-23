from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.repositories.operational import ProviderCredentialRepository, ProviderModelRepository, ProviderRepository
from app.repositories.shared import (
    TokenOwnedAutomationRecord,
    TokenOwnedCatalogRepository,
    TokenOwnedPromptRecord,
)
from app.services.execution_engine import ExecutionFormatterStrategy, ExecutionOutputType, ExecutionParserStrategy


@dataclass(slots=True)
class ExternalProviderRecord:
    id: uuid.UUID
    name: str
    slug: str | None
    is_active: bool


@dataclass(slots=True)
class ExternalProviderModelRecord:
    id: uuid.UUID
    provider_id: uuid.UUID
    name: str
    slug: str | None
    is_active: bool


@dataclass(slots=True)
class ExternalCredentialRecord:
    id: uuid.UUID
    provider_id: uuid.UUID
    name: str
    is_active: bool


class ExternalCatalogService:
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

    def __init__(self, *, shared_session: Session, operational_session: Session | None = None) -> None:
        self.shared_session = shared_session
        self.repository = TokenOwnedCatalogRepository(shared_session)
        self.operational_session = operational_session
        self.providers = ProviderRepository(operational_session) if operational_session is not None else None
        self.models = ProviderModelRepository(operational_session) if operational_session is not None else None
        self.credentials = ProviderCredentialRepository(operational_session) if operational_session is not None else None

    def list_automations(
        self,
        *,
        token_id: uuid.UUID,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[TokenOwnedAutomationRecord]:
        return self.repository.list_automations_by_token(
            token_id=token_id,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

    def get_automation_in_scope(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
    ) -> TokenOwnedAutomationRecord:
        item = self.repository.get_automation_by_id_and_token(
            automation_id=automation_id,
            token_id=token_id,
        )
        if item is None:
            raise AppException(
                "Automation not found in token scope.",
                status_code=404,
                code="automation_not_found_in_scope",
                details={"automation_id": str(automation_id)},
            )
        return item

    def create_automation(
        self,
        *,
        token_id: uuid.UUID,
        name: str,
        provider_id: uuid.UUID,
        model_id: uuid.UUID,
        credential_id: uuid.UUID | None = None,
        output_type: str | None = None,
        result_parser: str | None = None,
        result_formatter: str | None = None,
        output_schema: dict[str, Any] | None = None,
        is_active: bool = True,
    ) -> TokenOwnedAutomationRecord:
        self._validate_catalog_references(
            provider_id=provider_id,
            model_id=model_id,
            credential_id=credential_id,
        )
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise AppException(
                "Automation name cannot be empty.",
                status_code=422,
                code="validation_error",
                details={"field": "name"},
            )
        normalized_output_schema = self._normalize_output_schema(output_schema)
        try:
            item = self.repository.create_automation(
                token_id=token_id,
                name=normalized_name,
                provider_id=provider_id,
                model_id=model_id,
                credential_id=credential_id,
                output_type=self._normalize_output_type(output_type, default_if_none=True),
                result_parser=self._normalize_result_parser(result_parser, default_if_none=True),
                result_formatter=self._normalize_result_formatter(result_formatter, default_if_none=True),
                output_schema=normalized_output_schema,
                is_active=bool(is_active),
            )
            self.shared_session.commit()
            return item
        except Exception:
            self.shared_session.rollback()
            raise

    def update_automation(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
        changes: dict[str, Any],
    ) -> TokenOwnedAutomationRecord:
        current = self.get_automation_in_scope(token_id=token_id, automation_id=automation_id)
        normalized_changes = dict(changes or {})
        if "name" in normalized_changes:
            normalized_name = str(normalized_changes.get("name") or "").strip()
            if not normalized_name:
                raise AppException(
                    "Automation name cannot be empty.",
                    status_code=422,
                    code="validation_error",
                    details={"field": "name"},
                )
            normalized_changes["name"] = normalized_name
        if "provider_id" in normalized_changes and normalized_changes.get("provider_id") is None:
            raise AppException(
                "Provider cannot be null.",
                status_code=422,
                code="provider_not_found",
            )
        if "model_id" in normalized_changes and normalized_changes.get("model_id") is None:
            raise AppException(
                "Model cannot be null.",
                status_code=422,
                code="provider_model_not_found",
            )
        if "output_type" in normalized_changes:
            normalized_changes["output_type"] = self._normalize_output_type(
                normalized_changes.get("output_type"),
                default_if_none=False,
            )
        if "result_parser" in normalized_changes:
            normalized_changes["result_parser"] = self._normalize_result_parser(
                normalized_changes.get("result_parser"),
                default_if_none=False,
            )
        if "result_formatter" in normalized_changes:
            normalized_changes["result_formatter"] = self._normalize_result_formatter(
                normalized_changes.get("result_formatter"),
                default_if_none=False,
            )
        if "output_schema" in normalized_changes:
            normalized_changes["output_schema"] = self._normalize_output_schema(normalized_changes.get("output_schema"))

        next_provider_id = normalized_changes.get("provider_id", current.provider_id)
        next_model_id = normalized_changes.get("model_id", current.model_id)
        next_credential_id = normalized_changes.get("credential_id", current.credential_id)
        runtime_fields_changed = any(
            field_name in normalized_changes
            for field_name in (
                "provider_id",
                "model_id",
                "credential_id",
                "output_type",
                "result_parser",
                "result_formatter",
                "output_schema",
            )
        )
        has_runtime_ids = next_provider_id is not None and next_model_id is not None
        if runtime_fields_changed and not has_runtime_ids:
            raise AppException(
                "Automation runtime configuration requires provider and model.",
                status_code=422,
                code="automation_runtime_configuration_missing",
                details={"automation_id": str(automation_id), "missing_fields": ["provider", "model"]},
            )
        if has_runtime_ids:
            self._validate_catalog_references(
                provider_id=next_provider_id,
                model_id=next_model_id,
                credential_id=next_credential_id,
            )
        try:
            updated = self.repository.update_automation(
                token_id=token_id,
                automation_id=automation_id,
                changes=normalized_changes,
            )
            if updated is None:
                raise AppException(
                    "Automation not found in token scope.",
                    status_code=404,
                    code="automation_not_found_in_scope",
                    details={"automation_id": str(automation_id)},
                )
            self.shared_session.commit()
            return updated
        except Exception:
            self.shared_session.rollback()
            raise

    def delete_automation(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
    ) -> None:
        self.get_automation_in_scope(token_id=token_id, automation_id=automation_id)
        dependency_count = self.repository.count_prompts_for_automation(
            token_id=token_id,
            automation_id=automation_id,
        )
        if dependency_count > 0:
            raise AppException(
                "Deletion blocked: automation still has prompts.",
                status_code=409,
                code="delete_blocked_by_dependencies",
                details={"automation_id": str(automation_id), "prompt_count": dependency_count},
            )
        try:
            deleted = self.repository.delete_automation_by_id_and_token(
                token_id=token_id,
                automation_id=automation_id,
            )
            if not deleted:
                raise AppException(
                    "Automation not found in token scope.",
                    status_code=404,
                    code="automation_not_found_in_scope",
                    details={"automation_id": str(automation_id)},
                )
            self.shared_session.commit()
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

    def set_automation_status(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
        is_active: bool,
    ) -> TokenOwnedAutomationRecord:
        self.get_automation_in_scope(token_id=token_id, automation_id=automation_id)
        try:
            updated = self.repository.set_automation_status(
                token_id=token_id,
                automation_id=automation_id,
                is_active=is_active,
            )
            if updated is None:
                raise AppException(
                    "Automation not found in token scope.",
                    status_code=404,
                    code="automation_not_found_in_scope",
                    details={"automation_id": str(automation_id)},
                )
            self.shared_session.commit()
            return updated
        except Exception:
            self.shared_session.rollback()
            raise

    def list_external_providers(self, *, include_inactive: bool = True) -> list[ExternalProviderRecord]:
        providers, _, _ = self._require_operational_catalog()
        items = providers.list_all()
        if not include_inactive:
            items = [item for item in items if bool(item.is_active)]
        rows = [
            ExternalProviderRecord(
                id=item.id,
                name=str(item.name or "").strip(),
                slug=str(item.slug or "").strip() or None,
                is_active=bool(item.is_active),
            )
            for item in items
        ]
        rows.sort(key=lambda item: ((item.name or "").casefold(), str(item.id)))
        return rows

    def list_external_provider_models(
        self,
        *,
        provider_id: uuid.UUID,
        include_inactive: bool = True,
    ) -> list[ExternalProviderModelRecord]:
        providers, models, _ = self._require_operational_catalog()
        provider = providers.get_by_id(provider_id)
        if provider is None:
            raise AppException(
                "Provider not found in operational catalog.",
                status_code=404,
                code="provider_not_found",
                details={"provider_id": str(provider_id)},
            )
        items = models.list_by_provider(provider_id)
        if not include_inactive:
            items = [item for item in items if bool(item.is_active)]
        rows = [
            ExternalProviderModelRecord(
                id=item.id,
                provider_id=item.provider_id,
                name=str(item.model_name or "").strip(),
                slug=str(item.model_slug or "").strip() or None,
                is_active=bool(item.is_active),
            )
            for item in items
        ]
        rows.sort(key=lambda item: ((item.name or "").casefold(), str(item.id)))
        return rows

    def list_external_credentials(
        self,
        *,
        provider_id: uuid.UUID | None = None,
        include_inactive: bool = True,
    ) -> list[ExternalCredentialRecord]:
        providers, _, credentials = self._require_operational_catalog()
        provider_rows = providers.list_all()
        provider_index = {item.id: item for item in provider_rows}

        if provider_id is not None and provider_id not in provider_index:
            raise AppException(
                "Provider not found in operational catalog.",
                status_code=404,
                code="provider_not_found",
                details={"provider_id": str(provider_id)},
            )

        target_provider_ids = [provider_id] if provider_id is not None else list(provider_index.keys())
        rows: list[ExternalCredentialRecord] = []
        for current_provider_id in target_provider_ids:
            if current_provider_id is None:
                continue
            for item in credentials.list_by_provider(current_provider_id):
                if not include_inactive and not bool(item.is_active):
                    continue
                rows.append(
                    ExternalCredentialRecord(
                        id=item.id,
                        provider_id=item.provider_id,
                        name=str(item.credential_name or "").strip(),
                        is_active=bool(item.is_active),
                    )
                )
        rows.sort(key=lambda item: ((item.name or "").casefold(), str(item.id)))
        return rows

    def list_prompts(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[TokenOwnedPromptRecord]:
        if automation_id is not None:
            self.get_automation_in_scope(token_id=token_id, automation_id=automation_id)
        return self.repository.list_prompts_by_token(
            token_id=token_id,
            automation_id=automation_id,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

    def get_prompt_in_scope(
        self,
        *,
        token_id: uuid.UUID,
        prompt_id: uuid.UUID,
    ) -> TokenOwnedPromptRecord:
        item = self.repository.get_prompt_by_id_and_token(
            prompt_id=prompt_id,
            token_id=token_id,
        )
        if item is None:
            raise AppException(
                "Prompt not found in token scope.",
                status_code=404,
                code="prompt_not_found_in_scope",
                details={"prompt_id": str(prompt_id)},
            )
        return item

    def create_prompt(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
        prompt_text: str,
    ) -> TokenOwnedPromptRecord:
        scoped_automation = self.repository.get_automation_by_id_and_token(
            automation_id=automation_id,
            token_id=token_id,
        )
        if scoped_automation is None:
            unscoped = self.repository.get_automation_by_id(automation_id=automation_id)
            if unscoped is not None and unscoped.owner_token_id is not None and unscoped.owner_token_id != token_id:
                raise AppException(
                    "Target automation is outside authenticated token scope.",
                    status_code=403,
                    code="automation_out_of_scope",
                    details={"automation_id": str(automation_id)},
                )
            raise AppException(
                "Automation not found in token scope.",
                status_code=404,
                code="automation_not_found_in_scope",
                details={"automation_id": str(automation_id)},
            )

        try:
            item = self.repository.create_prompt(
                token_id=token_id,
                automation_id=scoped_automation.id,
                prompt_text=prompt_text,
            )
            self.shared_session.commit()
            return item
        except Exception:
            self.shared_session.rollback()
            raise

    def update_prompt(
        self,
        *,
        token_id: uuid.UUID,
        prompt_id: uuid.UUID,
        prompt_text: str | None = None,
        automation_id: uuid.UUID | None = None,
    ) -> TokenOwnedPromptRecord:
        self.get_prompt_in_scope(token_id=token_id, prompt_id=prompt_id)
        if automation_id is not None:
            self.get_automation_in_scope(token_id=token_id, automation_id=automation_id)
        try:
            updated = self.repository.update_prompt(
                token_id=token_id,
                prompt_id=prompt_id,
                prompt_text=prompt_text,
                automation_id=automation_id,
            )
            if updated is None:
                raise AppException(
                    "Prompt not found in token scope.",
                    status_code=404,
                    code="prompt_not_found_in_scope",
                    details={"prompt_id": str(prompt_id)},
                )
            self.shared_session.commit()
            return updated
        except IntegrityError as exc:
            self.shared_session.rollback()
            raise AppException(
                "Prompt update violates automation scope consistency.",
                status_code=409,
                code="automation_out_of_scope",
                details={"prompt_id": str(prompt_id), "reason": str(exc.orig) if exc.orig else str(exc)},
            ) from exc
        except Exception:
            self.shared_session.rollback()
            raise

    def delete_prompt(
        self,
        *,
        token_id: uuid.UUID,
        prompt_id: uuid.UUID,
    ) -> None:
        self.get_prompt_in_scope(token_id=token_id, prompt_id=prompt_id)
        try:
            deleted = self.repository.delete_prompt_by_id_and_token(
                token_id=token_id,
                prompt_id=prompt_id,
            )
            if not deleted:
                raise AppException(
                    "Prompt not found in token scope.",
                    status_code=404,
                    code="prompt_not_found_in_scope",
                    details={"prompt_id": str(prompt_id)},
                )
            self.shared_session.commit()
        except Exception:
            self.shared_session.rollback()
            raise

    def set_prompt_status(
        self,
        *,
        token_id: uuid.UUID,
        prompt_id: uuid.UUID,
        is_active: bool,
    ) -> TokenOwnedPromptRecord:
        self.get_prompt_in_scope(token_id=token_id, prompt_id=prompt_id)
        try:
            updated = self.repository.set_prompt_status(
                token_id=token_id,
                prompt_id=prompt_id,
                is_active=is_active,
            )
            if updated is None:
                raise AppException(
                    "Prompt not found in token scope.",
                    status_code=404,
                    code="prompt_not_found_in_scope",
                    details={"prompt_id": str(prompt_id)},
                )
            self.shared_session.commit()
            return updated
        except Exception:
            self.shared_session.rollback()
            raise

    def _require_operational_catalog(
        self,
    ) -> tuple[ProviderRepository, ProviderModelRepository, ProviderCredentialRepository]:
        if self.providers is None or self.models is None or self.credentials is None:
            raise AppException(
                "Operational catalog session is unavailable for this operation.",
                status_code=500,
                code="operational_catalog_unavailable",
            )
        return self.providers, self.models, self.credentials

    def _validate_catalog_references(
        self,
        *,
        provider_id: uuid.UUID,
        model_id: uuid.UUID,
        credential_id: uuid.UUID | None,
    ) -> None:
        providers, models, credentials = self._require_operational_catalog()
        provider = providers.get_by_id(provider_id)
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

        model = models.get_by_id(model_id)
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

        if credential_id is None:
            return
        credential = credentials.get_by_id(credential_id)
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

    @staticmethod
    def _normalize_output_schema(value: object | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise AppException(
                "Output schema is invalid: expected a JSON object.",
                status_code=422,
                code="execution_output_schema_invalid",
            )
        try:
            json.dumps(value)
        except TypeError as exc:
            raise AppException(
                "Output schema is invalid: payload is not JSON-serializable.",
                status_code=422,
                code="execution_output_schema_invalid",
            ) from exc
        return value
