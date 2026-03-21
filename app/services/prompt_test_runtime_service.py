from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class PromptTestRuntimeContext:
    automation_id: uuid.UUID
    automation_name: str
    automation_slug: str
    analysis_request_id: uuid.UUID
    created_automation: bool
    created_analysis_request: bool


@dataclass(slots=True, frozen=True)
class PromptTestManualAutomationContext:
    automation_id: uuid.UUID
    automation_name: str
    automation_slug: str | None
    provider_slug: str
    model_slug: str
    analysis_request_id: uuid.UUID


class PromptTestRuntimeService:
    """
    Garantia da automacao tecnica para execucao de prompts de teste.

    Responsabilidades:
    - localizar/criar automacao tecnica dedicada;
    - localizar/criar analysis_request associado;
    - retornar contexto pronto para execucao com prompt_override.
    """

    def __init__(self, shared_session: Session) -> None:
        self.shared_session = shared_session

    def ensure_runtime_context(self) -> PromptTestRuntimeContext:
        normalized_slug = str(settings.test_prompts_automation_slug or "").strip().lower() or "system-test-automation"
        normalized_name = str(settings.test_prompts_automation_name or "").strip() or "Automacao Tecnica de Teste"

        automation_columns = self._get_table_columns_metadata("automations")
        if not automation_columns:
            raise AppException(
                "Shared table 'automations' is unavailable for test runtime bootstrap.",
                status_code=500,
                code="test_prompt_runtime_unavailable",
            )
        analysis_columns = self._get_table_columns_metadata("analysis_requests")
        if not analysis_columns:
            raise AppException(
                "Shared table 'analysis_requests' is unavailable for test runtime bootstrap.",
                status_code=500,
                code="test_prompt_runtime_unavailable",
            )

        automation_row = self._find_technical_automation(
            slug=normalized_slug,
            name=normalized_name,
            automations_columns=automation_columns,
        )
        created_automation = False
        if automation_row is None:
            automation_row = self._create_technical_automation(
                slug=normalized_slug,
                name=normalized_name,
                automations_columns=automation_columns,
            )
            created_automation = True

        automation_id = self._coerce_uuid(automation_row.get("id"))
        if automation_id is None:
            raise AppException(
                "Technical test automation exists but its identifier is invalid.",
                status_code=500,
                code="test_prompt_runtime_invalid",
            )
        self._ensure_automation_active(
            automation_id=automation_id,
            automations_columns=automation_columns,
        )

        analysis_request_row = self._find_latest_analysis_request(
            automation_id=automation_id,
            analysis_columns=analysis_columns,
        )
        created_analysis_request = False
        if analysis_request_row is None:
            analysis_request_row = self._create_analysis_request_for_automation(
                automation_id=automation_id,
                analysis_columns=analysis_columns,
            )
            created_analysis_request = True

        analysis_request_id = self._coerce_uuid(analysis_request_row.get("id"))
        if analysis_request_id is None:
            raise AppException(
                "Technical test analysis_request exists but its identifier is invalid.",
                status_code=500,
                code="test_prompt_runtime_invalid",
            )

        return PromptTestRuntimeContext(
            automation_id=automation_id,
            automation_name=str(automation_row.get("name") or normalized_name).strip() or normalized_name,
            automation_slug=str(automation_row.get("slug") or normalized_slug).strip() or normalized_slug,
            analysis_request_id=analysis_request_id,
            created_automation=created_automation,
            created_analysis_request=created_analysis_request,
        )

    def create_manual_test_automation(
        self,
        *,
        automation_name: str,
        provider_slug: str,
        model_slug: str,
        provider_id: uuid.UUID | None = None,
        model_id: uuid.UUID | None = None,
    ) -> PromptTestManualAutomationContext:
        normalized_name = str(automation_name or "").strip()
        if not normalized_name:
            raise AppException(
                "Automation name is required.",
                status_code=422,
                code="invalid_test_automation_name",
            )
        normalized_provider = str(provider_slug or "").strip().lower()
        normalized_model = str(model_slug or "").strip().lower()
        if not normalized_provider or not normalized_model:
            raise AppException(
                "Provider/model runtime is required to create test automation.",
                status_code=422,
                code="invalid_test_automation_runtime",
            )

        automation_columns = self._get_table_columns_metadata("automations")
        if not automation_columns:
            raise AppException(
                "Shared table 'automations' is unavailable for test automation creation.",
                status_code=500,
                code="test_prompt_runtime_unavailable",
            )
        analysis_columns = self._get_table_columns_metadata("analysis_requests")
        if not analysis_columns:
            raise AppException(
                "Shared table 'analysis_requests' is unavailable for test automation creation.",
                status_code=500,
                code="test_prompt_runtime_unavailable",
            )

        created_row = self._create_manual_test_automation_row(
            name=normalized_name,
            provider_slug=normalized_provider,
            model_slug=normalized_model,
            provider_id=provider_id,
            model_id=model_id,
            automations_columns=automation_columns,
        )
        automation_id = self._coerce_uuid(created_row.get("id"))
        if automation_id is None:
            raise AppException(
                "Created test automation has invalid identifier.",
                status_code=500,
                code="test_prompt_runtime_invalid",
            )
        self._ensure_automation_active(
            automation_id=automation_id,
            automations_columns=automation_columns,
        )

        analysis_row = self._create_analysis_request_for_automation(
            automation_id=automation_id,
            analysis_columns=analysis_columns,
            apply_file_defaults=True,
        )
        analysis_request_id = self._coerce_uuid(analysis_row.get("id"))
        if analysis_request_id is None:
            raise AppException(
                "Created analysis_request has invalid identifier.",
                status_code=500,
                code="test_prompt_runtime_invalid",
            )

        return PromptTestManualAutomationContext(
            automation_id=automation_id,
            automation_name=str(created_row.get("name") or normalized_name).strip() or normalized_name,
            automation_slug=self._clean_text_value(created_row.get("slug")),
            provider_slug=normalized_provider,
            model_slug=normalized_model,
            analysis_request_id=analysis_request_id,
        )

    def _find_technical_automation(
        self,
        *,
        slug: str,
        name: str,
        automations_columns: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        selected_columns = self._automation_select_columns(automations_columns)
        preferred_id = self._configured_automation_id()
        if preferred_id is not None:
            stmt = text(
                f"SELECT {selected_columns} FROM automations WHERE id = :automation_id LIMIT 1"
            )
            row = self.shared_session.execute(stmt, {"automation_id": str(preferred_id)}).mappings().first()
            if row is not None:
                return dict(row)

        if "slug" in automations_columns:
            stmt = text(
                f"SELECT {selected_columns} FROM automations WHERE lower(slug) = :slug LIMIT 1"
            )
            row = self.shared_session.execute(stmt, {"slug": slug.lower()}).mappings().first()
            if row is not None:
                return dict(row)

        if "name" in automations_columns:
            stmt = text(
                f"SELECT {selected_columns} FROM automations WHERE lower(name) = :name LIMIT 1"
            )
            row = self.shared_session.execute(stmt, {"name": name.lower()}).mappings().first()
            if row is not None:
                return dict(row)
        return None

    def _create_technical_automation(
        self,
        *,
        slug: str,
        name: str,
        automations_columns: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        automation_id = self._configured_automation_id() or uuid.uuid4()
        values: dict[str, Any] = {}

        if "id" in automations_columns:
            values["id"] = automation_id
        if "name" in automations_columns:
            values["name"] = name
        if "slug" in automations_columns:
            values["slug"] = slug
        if "is_active" in automations_columns:
            values["is_active"] = True
        if "created_at" in automations_columns:
            values["created_at"] = now
        if "updated_at" in automations_columns:
            values["updated_at"] = now
        if "description" in automations_columns:
            values["description"] = "Automacao tecnica interna para prompts de teste."
        provider_column = self._first_existing_column(
            automations_columns,
            [
                "provider_slug",
                "provider",
                "ai_provider_slug",
                "ai_provider",
                "llm_provider",
                "provider_id",
                "ai_provider_id",
                "llm_provider_id",
            ],
        )
        model_column = self._first_existing_column(
            automations_columns,
            [
                "model_slug",
                "model",
                "ai_model_slug",
                "ai_model",
                "llm_model",
                "model_id",
                "ai_model_id",
                "llm_model_id",
            ],
        )
        if provider_column and model_column:
            default_runtime = self._resolve_default_provider_model(
                automations_columns=automations_columns,
                provider_column=provider_column,
                model_column=model_column,
            )
            if default_runtime is not None:
                values[provider_column] = default_runtime["provider_value"]
                values[model_column] = default_runtime["model_value"]

        required_columns = self._required_columns_without_default(automations_columns)
        for column_name in sorted(required_columns):
            if column_name in values:
                continue
            guessed = self._guess_value_for_required_column(
                table_name="automations",
                column_name=column_name,
                column_meta=automations_columns[column_name],
                now=now,
                automation_id=automation_id,
                automation_name=name,
                automation_slug=slug,
            )
            if guessed is None:
                raise AppException(
                    "Unable to auto-create technical test automation due to unsupported shared schema requirements.",
                    status_code=500,
                    code="test_prompt_runtime_schema_incompatible",
                    details={"missing_column": column_name},
                )
            values[column_name] = guessed

        inserted_row = self._insert_row(
            table_name="automations",
            values=values,
            select_columns=self._automation_select_columns(automations_columns),
            row_id_hint=automation_id,
            error_code="test_prompt_runtime_autocreate_failed",
            error_message="Failed to auto-create technical test automation in shared database.",
        )
        if inserted_row is None:
            raise AppException(
                "Failed to read technical test automation after creation.",
                status_code=500,
                code="test_prompt_runtime_invalid",
            )
        return inserted_row

    def _create_manual_test_automation_row(
        self,
        *,
        name: str,
        provider_slug: str,
        model_slug: str,
        provider_id: uuid.UUID | None,
        model_id: uuid.UUID | None,
        automations_columns: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        automation_id = uuid.uuid4()
        resolved_slug = self._build_test_automation_slug(
            automation_name=name,
            automations_columns=automations_columns,
        )
        values: dict[str, Any] = {}

        if "id" in automations_columns:
            values["id"] = automation_id
        if "name" in automations_columns:
            values["name"] = name
        if "slug" in automations_columns and resolved_slug is not None:
            values["slug"] = resolved_slug
        if "is_active" in automations_columns:
            values["is_active"] = True
        if "is_test" in automations_columns:
            values["is_test"] = True
        if "created_at" in automations_columns:
            values["created_at"] = now
        if "updated_at" in automations_columns:
            values["updated_at"] = now
        if "description" in automations_columns:
            values["description"] = "Automacao criada manualmente para execucao de prompt de teste."

        provider_column = self._first_existing_column(
            automations_columns,
            [
                "provider_slug",
                "provider",
                "ai_provider_slug",
                "ai_provider",
                "llm_provider",
                "provider_id",
                "ai_provider_id",
                "llm_provider_id",
            ],
        )
        model_column = self._first_existing_column(
            automations_columns,
            [
                "model_slug",
                "model",
                "ai_model_slug",
                "ai_model",
                "llm_model",
                "model_id",
                "ai_model_id",
                "llm_model_id",
            ],
        )
        if provider_column:
            provider_value = self._resolve_runtime_value_for_column(
                column_name=provider_column,
                column_meta=automations_columns[provider_column],
                slug_value=provider_slug,
                id_value=provider_id,
            )
            if provider_value is not None:
                values[provider_column] = provider_value
        if model_column:
            model_value = self._resolve_runtime_value_for_column(
                column_name=model_column,
                column_meta=automations_columns[model_column],
                slug_value=model_slug,
                id_value=model_id,
            )
            if model_value is not None:
                values[model_column] = model_value

        required_columns = self._required_columns_without_default(automations_columns)
        for column_name in sorted(required_columns):
            if column_name in values:
                continue
            guessed = self._guess_value_for_required_column(
                table_name="automations",
                column_name=column_name,
                column_meta=automations_columns[column_name],
                now=now,
                automation_id=automation_id,
                automation_name=name,
                automation_slug=resolved_slug or "",
            )
            if guessed is None:
                raise AppException(
                    "Unable to create test automation due to unsupported shared schema requirements.",
                    status_code=500,
                    code="test_prompt_runtime_schema_incompatible",
                    details={"missing_column": column_name},
                )
            values[column_name] = guessed

        inserted_row = self._insert_row(
            table_name="automations",
            values=values,
            select_columns=self._automation_select_columns(automations_columns),
            row_id_hint=automation_id,
            error_code="test_prompt_runtime_autocreate_failed",
            error_message="Failed to create test automation in shared database.",
        )
        if inserted_row is None:
            raise AppException(
                "Failed to read test automation after creation.",
                status_code=500,
                code="test_prompt_runtime_invalid",
            )
        return inserted_row

    def _ensure_automation_active(
        self,
        *,
        automation_id: uuid.UUID,
        automations_columns: dict[str, dict[str, Any]],
    ) -> None:
        if "is_active" not in automations_columns:
            return
        now = datetime.now(timezone.utc)
        assignments = ["is_active = true"]
        params: dict[str, Any] = {"automation_id": str(automation_id)}
        if "updated_at" in automations_columns:
            assignments.append("updated_at = :updated_at")
            params["updated_at"] = now
        stmt = text(
            f"""
            UPDATE automations
            SET {", ".join(assignments)}
            WHERE id = :automation_id
            """
        )
        self.shared_session.execute(stmt, params)
        self.shared_session.commit()

    def _find_latest_analysis_request(
        self,
        *,
        automation_id: uuid.UUID,
        analysis_columns: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        if "automation_id" not in analysis_columns:
            raise AppException(
                "Shared table 'analysis_requests' does not expose automation_id.",
                status_code=500,
                code="test_prompt_runtime_schema_incompatible",
            )
        order_by = "id DESC"
        if "created_at" in analysis_columns:
            order_by = "created_at DESC NULLS LAST, id DESC"
        stmt = text(
            f"""
            SELECT id
            FROM analysis_requests
            WHERE automation_id = :automation_id
            ORDER BY {order_by}
            LIMIT 1
            """
        )
        row = self.shared_session.execute(stmt, {"automation_id": str(automation_id)}).mappings().first()
        if row is None:
            return None
        return dict(row)

    def _create_analysis_request_for_automation(
        self,
        *,
        automation_id: uuid.UUID,
        analysis_columns: dict[str, dict[str, Any]],
        apply_file_defaults: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        request_id = uuid.uuid4()
        values: dict[str, Any] = {}

        if "id" in analysis_columns:
            values["id"] = request_id
        if "automation_id" in analysis_columns:
            values["automation_id"] = automation_id
        if "created_at" in analysis_columns:
            values["created_at"] = now
        if "updated_at" in analysis_columns:
            values["updated_at"] = now
        if apply_file_defaults:
            self._apply_analysis_request_file_defaults(
                values=values,
                analysis_columns=analysis_columns,
            )

        required_columns = self._required_columns_without_default(analysis_columns)
        for column_name in sorted(required_columns):
            if column_name in values:
                continue
            guessed = self._guess_value_for_required_column(
                table_name="analysis_requests",
                column_name=column_name,
                column_meta=analysis_columns[column_name],
                now=now,
                automation_id=automation_id,
                automation_name="",
                automation_slug="",
            )
            if guessed is None:
                raise AppException(
                    "Unable to auto-create analysis_request for technical test automation due to shared schema requirements.",
                    status_code=500,
                    code="test_prompt_analysis_request_schema_incompatible",
                    details={"missing_column": column_name},
                )
            values[column_name] = guessed

        inserted_row = self._insert_row(
            table_name="analysis_requests",
            values=values,
            select_columns="id",
            row_id_hint=request_id,
            error_code="test_prompt_analysis_request_autocreate_failed",
            error_message="Failed to auto-create analysis_request for technical test automation.",
        )
        if inserted_row is None:
            raise AppException(
                "Failed to read technical test analysis_request after creation.",
                status_code=500,
                code="test_prompt_runtime_invalid",
            )
        return inserted_row

    def _insert_row(
        self,
        *,
        table_name: str,
        values: dict[str, Any],
        select_columns: str,
        row_id_hint: uuid.UUID | None,
        error_code: str,
        error_message: str,
    ) -> dict[str, Any] | None:
        column_names = list(values.keys())
        placeholders = [f":{column_name}" for column_name in column_names]
        insert_stmt = text(
            f"""
            INSERT INTO {table_name} ({", ".join(column_names)})
            VALUES ({", ".join(placeholders)})
            """
        )
        try:
            self.shared_session.execute(insert_stmt, values)
            self.shared_session.commit()
        except Exception as exc:
            self.shared_session.rollback()
            logger.exception(
                "Failed to insert row into shared table for prompt test runtime.",
                extra={
                    "table": table_name,
                    "columns": sorted(column_names),
                    "row_id_hint": str(row_id_hint) if row_id_hint is not None else None,
                },
                exc_info=exc,
            )
            raise AppException(
                error_message,
                status_code=500,
                code=error_code,
                details={"table": table_name, "error": str(exc)},
            ) from exc

        if row_id_hint is None:
            return None
        fetch_stmt = text(
            f"SELECT {select_columns} FROM {table_name} WHERE id = :row_id LIMIT 1"
        )
        row = self.shared_session.execute(fetch_stmt, {"row_id": str(row_id_hint)}).mappings().first()
        if row is None:
            return None
        return dict(row)

    @staticmethod
    def _required_columns_without_default(columns: dict[str, dict[str, Any]]) -> set[str]:
        required: set[str] = set()
        for column_name, meta in columns.items():
            if str(meta.get("is_nullable") or "").upper() == "YES":
                continue
            if meta.get("column_default") is not None:
                continue
            required.add(column_name)
        return required

    @staticmethod
    def _automation_select_columns(automations_columns: dict[str, dict[str, Any]]) -> str:
        selected = ["id"]
        if "name" in automations_columns:
            selected.append("name")
        if "slug" in automations_columns:
            selected.append("slug")
        if "is_active" in automations_columns:
            selected.append("is_active")
        return ", ".join(selected)

    @staticmethod
    def _guess_value_for_required_column(
        *,
        table_name: str,
        column_name: str,
        column_meta: dict[str, Any],
        now: datetime,
        automation_id: uuid.UUID,
        automation_name: str,
        automation_slug: str,
    ) -> Any | None:
        lower_name = str(column_name).strip().lower()
        data_type = str(column_meta.get("data_type") or "").strip().lower()
        udt_name = str(column_meta.get("udt_name") or "").strip().lower()
        merged_type = f"{data_type} {udt_name}".strip()

        if lower_name == "id":
            return uuid.uuid4()
        if table_name == "analysis_requests" and lower_name == "automation_id":
            return automation_id
        if lower_name == "name" or lower_name.endswith("_name"):
            return automation_name or "Automacao Tecnica de Teste"
        if lower_name == "slug" or lower_name.endswith("_slug"):
            return automation_slug or "system-test-automation"
        if "provider" in lower_name or "model" in lower_name:
            return None
        if lower_name == "description":
            return "Automacao tecnica interna para prompts de teste."
        if lower_name in {"status", "state"}:
            return "created"
        if lower_name in {"source", "origin"}:
            return "system"
        if lower_name in {"type", "kind", "category"}:
            return "system_test"
        if lower_name in {"is_active", "active", "enabled"} or lower_name.startswith("is_"):
            return True
        if lower_name in {"created_at", "updated_at"} or lower_name.endswith("_at"):
            return now

        if "uuid" in merged_type:
            return uuid.uuid4()
        if "bool" in merged_type:
            return True
        if any(token in merged_type for token in ["int", "numeric", "decimal", "double", "real"]):
            return 1
        if "json" in merged_type:
            return {}
        if any(token in merged_type for token in ["char", "text", "varchar"]):
            return "system_test"
        if any(token in merged_type for token in ["timestamp", "date", "time"]):
            return now
        return None

    def _resolve_default_provider_model(
        self,
        *,
        automations_columns: dict[str, dict[str, Any]],
        provider_column: str,
        model_column: str,
    ) -> dict[str, Any] | None:
        active_filter = ""
        if "is_active" in automations_columns:
            active_filter = "AND coalesce(a.is_active, true) = true"
        stmt = text(
            f"""
            SELECT
                a.{provider_column} AS provider_value,
                a.{model_column} AS model_value
            FROM automations a
            WHERE a.{provider_column} IS NOT NULL
              AND a.{model_column} IS NOT NULL
              {active_filter}
            ORDER BY a.id ASC
            LIMIT 1
            """
        )
        row = self.shared_session.execute(stmt).mappings().first()
        if row is None:
            return None
        provider_value = row.get("provider_value")
        model_value = row.get("model_value")
        if provider_value is None or model_value is None:
            return None
        if not str(provider_value).strip() or not str(model_value).strip():
            return None
        return {"provider_value": provider_value, "model_value": model_value}

    def _resolve_runtime_value_for_column(
        self,
        *,
        column_name: str,
        column_meta: dict[str, Any],
        slug_value: str | None,
        id_value: uuid.UUID | None,
    ) -> Any | None:
        data_type = str(column_meta.get("data_type") or "").strip().lower()
        udt_name = str(column_meta.get("udt_name") or "").strip().lower()
        merged_type = f"{data_type} {udt_name}".strip()
        expects_uuid = "uuid" in merged_type
        expects_integer = any(token in merged_type for token in ["bigint", "smallint", "integer"])

        if self._column_prefers_identifier(column_name=column_name, column_meta=column_meta):
            if expects_integer:
                raw = str(slug_value or "").strip()
                if raw.isdigit():
                    try:
                        return int(raw)
                    except ValueError:
                        return None
                return None
            if id_value is not None:
                return id_value if expects_uuid else str(id_value)
            parsed_uuid = self._coerce_uuid(slug_value)
            if parsed_uuid is not None:
                return parsed_uuid if expects_uuid else str(parsed_uuid)
            return None
        normalized_slug = str(slug_value or "").strip()
        if normalized_slug:
            return normalized_slug
        if id_value is not None:
            return str(id_value)
        return None

    @staticmethod
    def _column_prefers_identifier(
        *,
        column_name: str,
        column_meta: dict[str, Any],
    ) -> bool:
        lower_name = str(column_name or "").strip().lower()
        data_type = str(column_meta.get("data_type") or "").strip().lower()
        udt_name = str(column_meta.get("udt_name") or "").strip().lower()
        merged_type = f"{data_type} {udt_name}".strip()
        if lower_name.endswith("_id"):
            return True
        if "uuid" in merged_type:
            return True
        return False

    def _build_test_automation_slug(
        self,
        *,
        automation_name: str,
        automations_columns: dict[str, dict[str, Any]],
    ) -> str | None:
        if "slug" not in automations_columns:
            return None
        base_slug = self._slugify_text(automation_name)
        if not base_slug:
            base_slug = "prompt-teste"
        prefix = "test-prompt-"
        candidate = f"{prefix}{base_slug}".strip("-")
        candidate = candidate[:100].strip("-")
        if not candidate:
            candidate = "test-prompt-automation"
        if not self._automation_slug_exists(candidate):
            return candidate
        for idx in range(2, 500):
            suffix = f"-{idx}"
            shortened = candidate[: max(1, 100 - len(suffix))].rstrip("-")
            current = f"{shortened}{suffix}"
            if not self._automation_slug_exists(current):
                return current
        return f"test-prompt-{uuid.uuid4().hex[:12]}"

    def _automation_slug_exists(self, slug: str) -> bool:
        stmt = text(
            """
            SELECT 1
            FROM automations
            WHERE lower(slug) = :slug
            LIMIT 1
            """
        )
        row = self.shared_session.execute(stmt, {"slug": str(slug or "").strip().lower()}).first()
        return row is not None

    def _apply_analysis_request_file_defaults(
        self,
        *,
        values: dict[str, Any],
        analysis_columns: dict[str, dict[str, Any]],
    ) -> None:
        allowed_extensions = ["xlsx", "csv", "txt", "pdf"]
        extension_csv = ",".join(allowed_extensions)
        allowed_mime_types = [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/csv",
            "text/plain",
            "application/pdf",
        ]

        for key in ["input_type", "request_input_type", "source_input_type"]:
            if key in analysis_columns:
                values[key] = "file"
                break

        for key in [
            "allowed_extensions",
            "accepted_extensions",
            "file_extensions",
            "allowed_file_extensions",
            "supported_extensions",
            "extensions",
        ]:
            if key not in analysis_columns:
                continue
            values[key] = self._adapt_list_value_for_column(
                values=allowed_extensions,
                fallback_csv=extension_csv,
                column_meta=analysis_columns[key],
            )
            break

        for key in [
            "allowed_mime_types",
            "accepted_mime_types",
            "mime_types",
            "supported_mime_types",
        ]:
            if key not in analysis_columns:
                continue
            values[key] = self._adapt_list_value_for_column(
                values=allowed_mime_types,
                fallback_csv=",".join(allowed_mime_types),
                column_meta=analysis_columns[key],
            )
            break

        for key in ["file_required", "requires_file", "is_file_required"]:
            if key in analysis_columns:
                values[key] = True
                break

    @staticmethod
    def _adapt_list_value_for_column(
        *,
        values: list[str],
        fallback_csv: str,
        column_meta: dict[str, Any],
    ) -> Any:
        data_type = str(column_meta.get("data_type") or "").strip().lower()
        udt_name = str(column_meta.get("udt_name") or "").strip().lower()
        merged = f"{data_type} {udt_name}".strip()
        if "array" in merged or udt_name.startswith("_"):
            return values
        if "json" in merged:
            return values
        return fallback_csv

    def _get_table_columns_metadata(self, table_name: str) -> dict[str, dict[str, Any]]:
        stmt = text(
            """
            SELECT
                c.column_name,
                c.is_nullable,
                c.column_default,
                c.data_type,
                c.udt_name
            FROM information_schema.columns c
            WHERE c.table_schema = current_schema()
              AND c.table_name = :table_name
            ORDER BY c.ordinal_position
            """
        )
        rows = self.shared_session.execute(stmt, {"table_name": table_name}).mappings().all()
        return {
            str(row["column_name"]): {
                "is_nullable": row.get("is_nullable"),
                "column_default": row.get("column_default"),
                "data_type": row.get("data_type"),
                "udt_name": row.get("udt_name"),
            }
            for row in rows
        }

    @staticmethod
    def _clean_text_value(value: Any) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _configured_automation_id() -> uuid.UUID | None:
        raw = str(settings.test_prompts_automation_id or "").strip()
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except ValueError as exc:
            raise AppException(
                "Invalid TEST_PROMPTS_AUTOMATION_ID format.",
                status_code=500,
                code="test_prompt_runtime_invalid_config",
                details={"test_prompts_automation_id": raw},
            ) from exc

    @staticmethod
    def _coerce_uuid(value: Any) -> uuid.UUID | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except ValueError:
            return None

    @staticmethod
    def _first_existing_column(
        columns: dict[str, dict[str, Any]],
        candidates: list[str],
    ) -> str | None:
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return None

    @staticmethod
    def _slugify_text(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
        normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
        return normalized
