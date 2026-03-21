from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.repositories.prompt_tests import PromptTestAutomationRecord, PromptTestAutomationRepository

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class PromptTestRuntimeContext:
    automation_id: uuid.UUID
    automation_name: str
    automation_slug: str | None
    provider_slug: str | None
    model_slug: str | None
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
    Runtime tecnico isolado para prompt tests.

    Regras de isolamento:
    - automacao de teste persiste exclusivamente em `test_automations`;
    - nenhuma escrita em `automations`;
    - nenhuma dependencia de FK/colunas do fluxo oficial de automacoes.
    """

    def __init__(self, shared_session: Session) -> None:
        self.shared_session = shared_session
        self.test_automations = PromptTestAutomationRepository(shared_session)

    def ensure_runtime_context(self) -> PromptTestRuntimeContext:
        self.test_automations.ensure_schema()

        normalized_slug = str(settings.test_prompts_automation_slug or "").strip().lower() or "system-test-automation"
        normalized_name = str(settings.test_prompts_automation_name or "").strip() or "Automacao Tecnica de Teste"
        preferred_id = self._configured_automation_id()

        runtime_row = self.test_automations.find_runtime(
            preferred_id=preferred_id,
            slug=normalized_slug,
            name=normalized_name,
        )
        created_automation = False
        if runtime_row is None:
            runtime_row = self.test_automations.create(
                automation_id=preferred_id or uuid.uuid4(),
                name=normalized_name,
                slug=normalized_slug,
                provider_slug=None,
                model_slug=None,
                provider_id=None,
                model_id=None,
                is_active=True,
            )
            created_automation = True
        elif not runtime_row.is_active:
            runtime_row = self.test_automations.update(
                automation_id=runtime_row.id,
                name=runtime_row.name,
                slug=runtime_row.slug or normalized_slug,
                provider_slug=runtime_row.provider_slug,
                model_slug=runtime_row.model_slug,
                provider_id=runtime_row.provider_id,
                model_id=runtime_row.model_id,
                is_active=True,
            )

        analysis_columns = self._get_table_columns_metadata("analysis_requests")
        if not analysis_columns:
            raise AppException(
                "Shared table 'analysis_requests' is unavailable for test runtime bootstrap.",
                status_code=500,
                code="test_prompt_runtime_unavailable",
            )

        analysis_request_row = self._find_latest_analysis_request(
            automation_id=runtime_row.id,
            analysis_columns=analysis_columns,
        )
        created_analysis_request = False
        if analysis_request_row is None:
            analysis_request_row = self._create_analysis_request_for_automation(
                automation_id=runtime_row.id,
                analysis_columns=analysis_columns,
                apply_file_defaults=True,
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
            automation_id=runtime_row.id,
            automation_name=runtime_row.name,
            automation_slug=runtime_row.slug,
            provider_slug=runtime_row.provider_slug,
            model_slug=runtime_row.model_slug,
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

        self.test_automations.ensure_schema()

        technical_slug = str(settings.test_prompts_automation_slug or "").strip().lower() or "system-test-automation"
        technical_name = str(settings.test_prompts_automation_name or "").strip() or "Automacao Tecnica de Teste"
        preferred_id = self._configured_automation_id()

        runtime_row = self.test_automations.find_runtime(
            preferred_id=preferred_id,
            slug=technical_slug,
            name=technical_name,
        )
        if runtime_row is None:
            runtime_row = self.test_automations.create(
                automation_id=preferred_id or uuid.uuid4(),
                name=normalized_name,
                slug=technical_slug,
                provider_slug=normalized_provider,
                model_slug=normalized_model,
                provider_id=provider_id,
                model_id=model_id,
                is_active=True,
            )
        else:
            runtime_row = self.test_automations.update(
                automation_id=runtime_row.id,
                name=normalized_name,
                slug=technical_slug,
                provider_slug=normalized_provider,
                model_slug=normalized_model,
                provider_id=provider_id,
                model_id=model_id,
                is_active=True,
            )

        analysis_columns = self._get_table_columns_metadata("analysis_requests")
        if not analysis_columns:
            raise AppException(
                "Shared table 'analysis_requests' is unavailable for test automation creation.",
                status_code=500,
                code="test_prompt_runtime_unavailable",
            )

        analysis_row = self._find_latest_analysis_request(
            automation_id=runtime_row.id,
            analysis_columns=analysis_columns,
        )
        if analysis_row is None:
            analysis_row = self._create_analysis_request_for_automation(
                automation_id=runtime_row.id,
                analysis_columns=analysis_columns,
                apply_file_defaults=True,
            )

        analysis_request_id = self._coerce_uuid(analysis_row.get("id"))
        if analysis_request_id is None:
            raise AppException(
                "Test automation analysis_request has invalid identifier.",
                status_code=500,
                code="test_prompt_runtime_invalid",
            )

        return PromptTestManualAutomationContext(
            automation_id=runtime_row.id,
            automation_name=runtime_row.name,
            automation_slug=runtime_row.slug,
            provider_slug=normalized_provider,
            model_slug=normalized_model,
            analysis_request_id=analysis_request_id,
        )

    def get_test_automation_by_id(self, automation_id: uuid.UUID) -> PromptTestAutomationRecord | None:
        self.test_automations.ensure_schema()
        return self.test_automations.get_by_id(automation_id)

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
            return automation_slug or "prompt-test-runtime"
        if "provider" in lower_name or "model" in lower_name:
            return None
        if lower_name == "description":
            return "Runtime tecnico interno para prompts de teste."
        if lower_name in {"status", "state"}:
            return "created"
        if lower_name in {"source", "origin"}:
            return "prompt_test_runtime"
        if lower_name in {"type", "kind", "category"}:
            return "prompt_test_runtime"
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
            return "prompt_test_runtime"
        if any(token in merged_type for token in ["timestamp", "date", "time"]):
            return now
        return None

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
