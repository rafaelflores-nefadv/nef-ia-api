from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException

settings = get_settings()


@dataclass(slots=True, frozen=True)
class PromptTestRuntimeContext:
    automation_id: uuid.UUID
    automation_name: str
    automation_slug: str
    analysis_request_id: uuid.UUID
    created_automation: bool
    created_analysis_request: bool


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
            ["provider_slug", "provider", "ai_provider_slug", "ai_provider", "llm_provider"],
        )
        model_column = self._first_existing_column(
            automations_columns,
            ["model_slug", "model", "ai_model_slug", "ai_model", "llm_model"],
        )
        if provider_column and model_column:
            default_runtime = self._resolve_default_provider_model(
                automations_columns=automations_columns,
                provider_column=provider_column,
                model_column=model_column,
            )
            if default_runtime is not None:
                values[provider_column] = default_runtime["provider_slug"]
                values[model_column] = default_runtime["model_slug"]

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
    ) -> dict[str, str] | None:
        active_filter = ""
        if "is_active" in automations_columns:
            active_filter = "AND coalesce(a.is_active, true) = true"
        stmt = text(
            f"""
            SELECT
                a.{provider_column} AS provider_slug,
                a.{model_column} AS model_slug
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
        provider_slug = str(row.get("provider_slug") or "").strip()
        model_slug = str(row.get("model_slug") or "").strip()
        if not provider_slug or not model_slug:
            return None
        return {"provider_slug": provider_slug, "model_slug": model_slug}

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
