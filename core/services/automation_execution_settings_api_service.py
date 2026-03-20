from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from .api_client import ApiResponse, FastAPIClient


def _to_uuid(value: Any) -> UUID | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


@dataclass
class AutomationExecutionSettingReadItem:
    automation_id: UUID
    automation_name: str
    automation_is_active: bool
    persisted_setting_id: UUID | None
    persisted_is_active: bool | None
    persisted_execution_profile: str | None
    persisted_limits_overrides: dict[str, int]
    resolved_execution_profile: str
    resolved_profile_source: str
    resolved_profile_source_details: dict[str, Any]
    resolved_limits: dict[str, int]
    hard_clamped_fields: list[str]
    hard_clamp_details: dict[str, dict[str, int]]
    source_label: str
    source_css_class: str


class AutomationExecutionSettingsAPIServiceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class AutomationExecutionSettingsAPIService:
    def __init__(self, *, client: FastAPIClient | None = None) -> None:
        self.client = client or FastAPIClient()

    @staticmethod
    def _extract_error_meta(result: ApiResponse) -> tuple[str | None, str]:
        code: str | None = None
        message = str(result.error or "").strip()
        if isinstance(result.data, dict):
            error_payload = result.data.get("error")
            if isinstance(error_payload, dict):
                payload_code = str(error_payload.get("code") or "").strip()
                if payload_code:
                    code = payload_code
                payload_message = str(error_payload.get("message") or "").strip()
                if payload_message:
                    message = payload_message
        return code, message

    @staticmethod
    def _source_meta(source: str) -> tuple[str, str]:
        normalized = str(source or "").strip().lower()
        table = {
            "persisted_automation": ("Persistido na automacao", "status-success"),
            "persisted_automation_fallback_standard": ("Persistido (fallback standard)", "status-warning"),
            "env_automation_override": ("Override por env", "status-warning"),
            "env_automation_override_fallback_standard": ("Env override (fallback standard)", "status-warning"),
            "env_default": ("Default por env", "status-neutral"),
            "env_default_fallback_standard": ("Default env (fallback standard)", "status-neutral"),
            "fallback_standard": ("Fallback seguro", "status-neutral"),
        }
        return table.get(normalized, ("Origem nao mapeada", "status-neutral"))

    @classmethod
    def _normalize_item(cls, row: dict[str, Any]) -> AutomationExecutionSettingReadItem | None:
        automation_id = _to_uuid(row.get("automation_id"))
        if automation_id is None:
            return None

        persisted_setting_id = _to_uuid(row.get("persisted_setting_id"))
        persisted_overrides_raw = row.get("persisted_limits_overrides")
        persisted_overrides: dict[str, int] = {}
        if isinstance(persisted_overrides_raw, dict):
            for key, value in persisted_overrides_raw.items():
                try:
                    persisted_overrides[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue

        resolved_limits_raw = row.get("resolved_limits")
        resolved_limits: dict[str, int] = {}
        if isinstance(resolved_limits_raw, dict):
            for key, value in resolved_limits_raw.items():
                try:
                    resolved_limits[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue

        hard_clamp_details_raw = row.get("hard_clamp_details")
        hard_clamp_details: dict[str, dict[str, int]] = {}
        if isinstance(hard_clamp_details_raw, dict):
            for key, value in hard_clamp_details_raw.items():
                if not isinstance(value, dict):
                    continue
                profile_value = value.get("profile_value")
                hard_limit = value.get("hard_limit")
                try:
                    hard_clamp_details[str(key)] = {
                        "profile_value": int(profile_value),
                        "hard_limit": int(hard_limit),
                    }
                except (TypeError, ValueError):
                    continue

        source = str(row.get("resolved_profile_source") or "").strip()
        source_label, source_css_class = cls._source_meta(source)

        source_details_raw = row.get("resolved_profile_source_details")
        source_details: dict[str, Any] = source_details_raw if isinstance(source_details_raw, dict) else {}

        hard_clamped_raw = row.get("hard_clamped_fields")
        hard_clamped_fields = []
        if isinstance(hard_clamped_raw, list):
            hard_clamped_fields = [str(item) for item in hard_clamped_raw if str(item).strip()]

        return AutomationExecutionSettingReadItem(
            automation_id=automation_id,
            automation_name=str(row.get("automation_name") or "").strip() or str(automation_id),
            automation_is_active=bool(row.get("automation_is_active", False)),
            persisted_setting_id=persisted_setting_id,
            persisted_is_active=(
                None if row.get("persisted_is_active") is None else bool(row.get("persisted_is_active"))
            ),
            persisted_execution_profile=(
                str(row.get("persisted_execution_profile") or "").strip() or None
            ),
            persisted_limits_overrides=persisted_overrides,
            resolved_execution_profile=str(row.get("resolved_execution_profile") or "").strip() or "standard",
            resolved_profile_source=source,
            resolved_profile_source_details=source_details,
            resolved_limits=resolved_limits,
            hard_clamped_fields=hard_clamped_fields,
            hard_clamp_details=hard_clamp_details,
            source_label=source_label,
            source_css_class=source_css_class,
        )

    def _friendly_error(
        self,
        *,
        code: str | None,
        status_code: int | None,
        fallback_message: str,
        action: str,
    ) -> str:
        if code == "automation_not_found":
            return "Automacao nao encontrada na FastAPI."
        if code == "execution_profile_invalid":
            return "Perfil de execucao invalido. Use standard, heavy ou extended."
        if code in {"automation_execution_override_invalid", "automation_execution_override_above_hard_limit"}:
            return "Override invalido para os limites operacionais."
        if code in {"invalid_integration_token", "deactivated_integration_token"}:
            return "Token de integracao FastAPI invalido ou desativado."
        if status_code in {401, 403}:
            return "Falha de autenticacao/permissao ao acessar configuracoes de execucao."
        if status_code == 404:
            return "Recurso nao encontrado na FastAPI."
        if status_code is None:
            return fallback_message or "Falha de comunicacao com a FastAPI."
        return fallback_message or f"Falha ao {action} na FastAPI (HTTP {status_code})."

    def list_settings(self) -> dict[str, Any]:
        result = self.client.get(
            "/api/v1/admin/automation-execution-settings",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        warnings: list[str] = []

        if result.is_success and isinstance(result.data, dict):
            raw_items = result.data.get("items")
            items: list[AutomationExecutionSettingReadItem] = []
            if isinstance(raw_items, list):
                for row in raw_items:
                    if not isinstance(row, dict):
                        continue
                    item = self._normalize_item(row)
                    if item is not None:
                        items.append(item)
            return {
                "source": "api",
                "warnings": warnings,
                "items": items,
            }

        code, message = self._extract_error_meta(result)
        warnings.append(
            self._friendly_error(
                code=code,
                status_code=result.status_code,
                fallback_message=message,
                action="listar configuracoes operacionais",
            )
        )
        return {
            "source": "unavailable",
            "warnings": warnings,
            "items": [],
        }

    def get_setting(self, *, automation_id: UUID) -> AutomationExecutionSettingReadItem:
        result = self.client.get(
            f"/api/v1/admin/automation-execution-settings/{automation_id}",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success or not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise AutomationExecutionSettingsAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="consultar configuracao operacional",
                ),
                code=code,
                status_code=result.status_code,
            )

        item = self._normalize_item(result.data)
        if item is None:
            raise AutomationExecutionSettingsAPIServiceError(
                "Resposta invalida da FastAPI ao consultar configuracao operacional.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        return item

    def update_setting(
        self,
        *,
        automation_id: UUID,
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
    ) -> AutomationExecutionSettingReadItem:
        payload = {
            "execution_profile": str(execution_profile or "").strip().lower(),
            "is_active": bool(is_active),
            "max_execution_rows": max_execution_rows,
            "max_provider_calls": max_provider_calls,
            "max_text_chunks": max_text_chunks,
            "max_tabular_row_characters": max_tabular_row_characters,
            "max_execution_seconds": max_execution_seconds,
            "max_context_characters": max_context_characters,
            "max_context_file_characters": max_context_file_characters,
            "max_prompt_characters": max_prompt_characters,
        }
        result = self.client.put(
            f"/api/v1/admin/automation-execution-settings/{automation_id}",
            json_body=payload,
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success or not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise AutomationExecutionSettingsAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="salvar configuracao operacional",
                ),
                code=code,
                status_code=result.status_code,
            )

        item = self._normalize_item(result.data)
        if item is None:
            raise AutomationExecutionSettingsAPIServiceError(
                "Resposta invalida da FastAPI ao salvar configuracao operacional.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        return item
