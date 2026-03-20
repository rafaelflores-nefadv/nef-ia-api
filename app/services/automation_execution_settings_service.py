import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.models.operational import DjangoAiAuditLog, DjangoAiAutomationExecutionSetting
from app.repositories.operational import AuditLogRepository, AutomationExecutionSettingsRepository
from app.repositories.shared import SharedAutomationRepository
from app.services.execution_service import (
    KNOWN_EXECUTION_PROFILES,
    PROFILE_STANDARD,
    ExecutionService,
)


class AutomationExecutionSettingsService:
    def __init__(
        self,
        *,
        operational_session: Session,
        shared_session: Session,
    ) -> None:
        self.operational_session = operational_session
        self.shared_session = shared_session
        self.settings_repository = AutomationExecutionSettingsRepository(operational_session)
        self.audit_repository = AuditLogRepository(operational_session)
        self.automations_repository = SharedAutomationRepository(shared_session)
        self.execution_service = ExecutionService(
            operational_session=operational_session,
            shared_session=shared_session,
        )

    @staticmethod
    def _normalize_profile_name(value: str | None) -> str:
        return str(value or "").strip().lower()

    def _validate_profile_name(self, profile_name: str) -> str:
        normalized = self._normalize_profile_name(profile_name)
        if normalized not in KNOWN_EXECUTION_PROFILES:
            raise AppException(
                "Invalid execution profile. Allowed values: standard, heavy, extended.",
                status_code=422,
                code="execution_profile_invalid",
                details={
                    "execution_profile": normalized or "(empty)",
                    "allowed_profiles": sorted(KNOWN_EXECUTION_PROFILES),
                },
            )
        return normalized

    def _validate_overrides_against_hard_limits(self, *, overrides: dict[str, int | None]) -> None:
        hard_ceilings = self.execution_service._hard_limit_ceilings()
        for limit_key, raw_value in overrides.items():
            if raw_value is None:
                continue
            try:
                requested_value = int(raw_value)
            except (TypeError, ValueError):
                raise AppException(
                    "Invalid override value; expected positive integer.",
                    status_code=422,
                    code="automation_execution_override_invalid",
                    details={
                        "limit_key": limit_key,
                        "value": raw_value,
                    },
                ) from None
            if requested_value <= 0:
                raise AppException(
                    "Invalid override value; expected positive integer.",
                    status_code=422,
                    code="automation_execution_override_invalid",
                    details={
                        "limit_key": limit_key,
                        "value": requested_value,
                    },
                )

            hard_limit = int(hard_ceilings.get(limit_key, 0))
            if hard_limit <= 0:
                continue
            if requested_value > hard_limit:
                raise AppException(
                    "Persisted override exceeds global hard limit.",
                    status_code=422,
                    code="automation_execution_override_above_hard_limit",
                    details={
                        "limit_key": limit_key,
                        "requested_value": requested_value,
                        "hard_limit": hard_limit,
                    },
                )

    @staticmethod
    def _resolved_payload(
        *,
        automation_id: uuid.UUID,
        automation_name: str,
        automation_is_active: bool,
        persisted_setting: DjangoAiAutomationExecutionSetting | None,
        resolved_profile,
    ) -> dict[str, Any]:
        persisted_overrides: dict[str, int] = {}
        if persisted_setting is not None:
            persisted_overrides = {
                key: int(value)
                for key, value in {
                    "max_execution_rows": persisted_setting.max_execution_rows,
                    "max_provider_calls": persisted_setting.max_provider_calls,
                    "max_text_chunks": persisted_setting.max_text_chunks,
                    "max_tabular_row_characters": persisted_setting.max_tabular_row_characters,
                    "max_execution_seconds": persisted_setting.max_execution_seconds,
                    "max_context_characters": persisted_setting.max_context_characters,
                    "max_context_file_characters": persisted_setting.max_context_file_characters,
                    "max_prompt_characters": persisted_setting.max_prompt_characters,
                }.items()
                if value is not None
            }

        return {
            "automation_id": automation_id,
            "automation_name": automation_name,
            "automation_is_active": bool(automation_is_active),
            "persisted_setting_id": persisted_setting.id if persisted_setting is not None else None,
            "persisted_is_active": persisted_setting.is_active if persisted_setting is not None else None,
            "persisted_execution_profile": persisted_setting.execution_profile if persisted_setting is not None else None,
            "persisted_limits_overrides": persisted_overrides,
            "resolved_execution_profile": resolved_profile.name,
            "resolved_profile_source": resolved_profile.source,
            "resolved_profile_source_details": resolved_profile.source_details,
            "resolved_limits": resolved_profile.to_limits_dict(),
            "hard_clamped_fields": list(resolved_profile.hard_clamped_fields),
            "hard_clamp_details": resolved_profile.hard_clamp_details,
        }

    def list_automation_settings(self) -> list[dict[str, Any]]:
        persisted_rows = self.settings_repository.list_all()
        persisted_map = {item.automation_id: item for item in persisted_rows}

        items: list[dict[str, Any]] = []
        for automation in self.automations_repository.list_automations():
            persisted_setting = persisted_map.get(automation.id)
            resolved_profile = self.execution_service._resolve_execution_profile(automation_id=automation.id)
            items.append(
                self._resolved_payload(
                    automation_id=automation.id,
                    automation_name=str(automation.name or "").strip() or str(automation.id),
                    automation_is_active=bool(automation.is_active),
                    persisted_setting=persisted_setting,
                    resolved_profile=resolved_profile,
                )
            )
        return items

    def get_automation_setting(self, *, automation_id: uuid.UUID) -> dict[str, Any]:
        automation = self.automations_repository.get_automation_by_id(automation_id)
        if automation is None:
            raise AppException(
                "Automation not found.",
                status_code=404,
                code="automation_not_found",
                details={"automation_id": str(automation_id)},
            )

        persisted_setting = self.settings_repository.get_by_automation_id(automation_id)
        resolved_profile = self.execution_service._resolve_execution_profile(automation_id=automation_id)
        return self._resolved_payload(
            automation_id=automation.id,
            automation_name=str(automation.name or "").strip() or str(automation.id),
            automation_is_active=bool(automation.is_active),
            persisted_setting=persisted_setting,
            resolved_profile=resolved_profile,
        )

    def upsert_automation_setting(
        self,
        *,
        automation_id: uuid.UUID,
        execution_profile: str,
        is_active: bool,
        max_execution_rows: int | None,
        max_provider_calls: int | None,
        max_text_chunks: int | None,
        max_tabular_row_characters: int | None,
        max_execution_seconds: int | None,
        max_context_characters: int | None,
        max_context_file_characters: int | None,
        max_prompt_characters: int | None,
        actor_user_id: uuid.UUID,
        ip_address: str | None,
    ) -> dict[str, Any]:
        automation = self.automations_repository.get_automation_by_id(automation_id)
        if automation is None:
            raise AppException(
                "Automation not found.",
                status_code=404,
                code="automation_not_found",
                details={"automation_id": str(automation_id)},
            )

        normalized_profile = self._validate_profile_name(execution_profile)
        overrides = {
            "max_execution_rows": max_execution_rows,
            "max_provider_calls": max_provider_calls,
            "max_text_chunks": max_text_chunks,
            "max_tabular_row_characters": max_tabular_row_characters,
            "max_execution_seconds": max_execution_seconds,
            "max_context_characters": max_context_characters,
            "max_context_file_characters": max_context_file_characters,
            "max_prompt_characters": max_prompt_characters,
        }
        self._validate_overrides_against_hard_limits(overrides=overrides)

        persisted_setting = self.settings_repository.get_by_automation_id(automation_id)
        is_creation = persisted_setting is None
        if persisted_setting is None:
            persisted_setting = DjangoAiAutomationExecutionSetting(
                automation_id=automation_id,
                execution_profile=PROFILE_STANDARD,
                is_active=True,
            )
            self.settings_repository.add(persisted_setting)

        persisted_setting.execution_profile = normalized_profile
        persisted_setting.is_active = bool(is_active)
        persisted_setting.max_execution_rows = max_execution_rows
        persisted_setting.max_provider_calls = max_provider_calls
        persisted_setting.max_text_chunks = max_text_chunks
        persisted_setting.max_tabular_row_characters = max_tabular_row_characters
        persisted_setting.max_execution_seconds = max_execution_seconds
        persisted_setting.max_context_characters = max_context_characters
        persisted_setting.max_context_file_characters = max_context_file_characters
        persisted_setting.max_prompt_characters = max_prompt_characters

        self.audit_repository.add(
            DjangoAiAuditLog(
                action_type="automation_execution_setting_upserted",
                entity_type="django_ai_automation_execution_settings",
                entity_id=str(persisted_setting.id),
                performed_by_user_id=actor_user_id,
                changes_json={
                    "automation_id": str(automation_id),
                    "mode": "create" if is_creation else "update",
                    "execution_profile": normalized_profile,
                    "is_active": bool(is_active),
                    "overrides": {key: value for key, value in overrides.items() if value is not None},
                },
                ip_address=ip_address,
            )
        )
        self.operational_session.commit()
        self.operational_session.refresh(persisted_setting)

        return self.get_automation_setting(automation_id=automation_id)
