from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from typing import Any
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.models.shared import AutomationPrompt

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SharedAutomationRecord:
    id: uuid.UUID
    name: str
    is_active: bool
    owner_token_id: uuid.UUID | None


@dataclass(slots=True)
class SharedAutomationRuntimeRecord:
    automation_id: uuid.UUID
    prompt_id: uuid.UUID | None
    prompt_text: str
    prompt_is_active: bool | None
    prompt_version: int
    automation_slug: str | None
    is_test_automation: bool | None
    provider_id: uuid.UUID | None
    model_id: uuid.UUID | None
    provider_slug: str | None
    model_slug: str | None
    credential_id: str | None
    credential_name: str | None
    output_type: str | None
    result_parser: str | None
    result_formatter: str | None
    output_schema: dict[str, Any] | str | None
    debug_enabled: bool | None


@dataclass(slots=True)
class SharedAutomationTargetRecord:
    automation_id: uuid.UUID
    automation_slug: str | None
    is_test_automation: bool | None
    provider_id: uuid.UUID | None
    model_id: uuid.UUID | None
    provider_slug: str | None
    model_slug: str | None
    credential_id: str | None
    output_type: str | None
    result_parser: str | None
    result_formatter: str | None
    output_schema: dict[str, Any] | str | None
    debug_enabled: bool | None


class SharedAutomationRepository:
    """Repository for general-system automation data (source of truth)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_automation_by_id(self, automation_id: uuid.UUID) -> SharedAutomationRecord | None:
        automation_columns = self._get_table_columns("automations")
        if "id" not in automation_columns:
            return None

        stmt = text(
            f"""
            SELECT {self._build_automation_select_sql(table_alias="a", available_columns=automation_columns)}
            FROM automations a
            WHERE a.id = :automation_id
            LIMIT 1
            """
        )
        row = self.session.execute(stmt, {"automation_id": str(automation_id)}).mappings().first()
        return self._build_automation_record(row, available_columns=automation_columns)

    def list_automations(self) -> list[SharedAutomationRecord]:
        automation_columns = self._get_table_columns("automations")
        if "id" not in automation_columns:
            return []

        if "name" in automation_columns:
            order_by = "a.name ASC, a.id ASC"
        else:
            order_by = "a.id ASC"

        stmt = text(
            f"""
            SELECT {self._build_automation_select_sql(table_alias="a", available_columns=automation_columns)}
            FROM automations a
            ORDER BY {order_by}
            """
        )
        rows = self.session.execute(stmt).mappings().all()
        items: list[SharedAutomationRecord] = []
        for row in rows:
            item = self._build_automation_record(row, available_columns=automation_columns)
            if item is not None:
                items.append(item)
        return items

    def find_automation_by_slug_or_name(
        self,
        *,
        slug: str | None,
        name: str | None,
    ) -> SharedAutomationRecord | None:
        automation_columns = self._get_table_columns("automations")
        normalized_slug = str(slug or "").strip().lower()
        normalized_name = str(name or "").strip().lower()
        if "id" not in automation_columns:
            return None

        select_sql = self._build_automation_select_sql(
            table_alias="a",
            available_columns=automation_columns,
        )

        if normalized_slug:
            slug_column = next(
                (
                    candidate
                    for candidate in ["slug", "automation_slug", "key", "code"]
                    if candidate in automation_columns
                ),
                None,
            )
            if slug_column is not None:
                stmt = text(
                    f"""
                    SELECT {select_sql}
                    FROM automations a
                    WHERE lower(a.{slug_column}) = :slug
                    LIMIT 1
                    """
                )
                row = self.session.execute(stmt, {"slug": normalized_slug}).mappings().first()
                item = self._build_automation_record(row, available_columns=automation_columns)
                if item is not None:
                    return item

        if normalized_name and "name" in automation_columns:
            stmt = text(
                f"""
                SELECT {select_sql}
                FROM automations a
                WHERE lower(a.name) = :name
                LIMIT 1
                """
            )
            row = self.session.execute(stmt, {"name": normalized_name}).mappings().first()
            item = self._build_automation_record(row, available_columns=automation_columns)
            if item is not None:
                return item
        return None

    def ensure_technical_automation(
        self,
        *,
        preferred_id: uuid.UUID | None,
        slug: str,
        name: str,
    ) -> SharedAutomationRecord:
        metadata = self._get_table_columns_metadata("automations")
        if "id" not in metadata:
            raise AppException(
                "Shared table 'automations' is unavailable for prompt-test runtime bootstrap.",
                status_code=500,
                code="test_prompt_runtime_shared_automation_schema_incompatible",
            )

        existing = self.get_automation_by_id(preferred_id) if preferred_id is not None else None
        if existing is None:
            existing = self.find_automation_by_slug_or_name(slug=slug, name=name)

        if existing is None:
            automation_id = preferred_id or uuid.uuid4()
            try:
                existing = self._create_technical_automation(
                    automation_id=automation_id,
                    slug=slug,
                    name=name,
                    metadata=metadata,
                )
            except AppException:
                existing = self.get_automation_by_id(automation_id)
                if existing is None:
                    existing = self.find_automation_by_slug_or_name(slug=slug, name=name)
                if existing is None:
                    raise

        return self._normalize_technical_automation(
            automation_id=existing.id,
            slug=slug,
            name=name,
            metadata=metadata,
        )

    def get_latest_prompt_for_automation(self, automation_id: uuid.UUID) -> AutomationPrompt | None:
        stmt = (
            select(AutomationPrompt)
            .where(AutomationPrompt.automation_id == automation_id)
            .order_by(AutomationPrompt.version.desc(), AutomationPrompt.created_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_runtime_config_for_automation(self, automation_id: uuid.UUID) -> SharedAutomationRuntimeRecord | None:
        prompt_columns = self._get_table_columns("automation_prompts")
        automation_columns = self._get_table_columns("automations")

        prompt_id_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=["id"],
            default_sql="NULL::uuid",
        )
        prompt_active_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=["is_active", "active", "enabled"],
            default_sql="NULL::boolean",
        )
        prompt_provider_id_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=[
                "provider_id",
                "ai_provider_id",
                "llm_provider_id",
            ],
            default_sql="NULL::text",
        )
        prompt_provider_slug_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=[
                "provider_slug",
                "provider",
                "ai_provider_slug",
                "ai_provider",
                "llm_provider",
            ],
        )
        prompt_model_id_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=[
                "model_id",
                "ai_model_id",
                "llm_model_id",
            ],
            default_sql="NULL::text",
        )
        prompt_model_slug_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=[
                "model_slug",
                "model",
                "ai_model_slug",
                "ai_model",
                "llm_model",
            ],
        )
        prompt_credential_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=["credential_id", "provider_credential_id", "ai_credential_id", "llm_credential_id"],
        )
        prompt_credential_name_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=["credential_name", "provider_credential_name", "ai_credential_name", "llm_credential_name"],
            default_sql="NULL::text",
        )
        automation_provider_id_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=[
                "provider_id",
                "ai_provider_id",
                "llm_provider_id",
            ],
            default_sql="NULL::text",
        )
        automation_provider_slug_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=[
                "provider_slug",
                "provider",
                "ai_provider_slug",
                "ai_provider",
                "llm_provider",
            ],
        )
        automation_model_id_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=[
                "model_id",
                "ai_model_id",
                "llm_model_id",
            ],
            default_sql="NULL::text",
        )
        automation_model_slug_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=[
                "model_slug",
                "model",
                "ai_model_slug",
                "ai_model",
                "llm_model",
            ],
        )
        automation_credential_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["credential_id", "provider_credential_id", "ai_credential_id", "llm_credential_id"],
        )
        automation_credential_name_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["credential_name", "provider_credential_name", "ai_credential_name", "llm_credential_name"],
            default_sql="NULL::text",
        )
        prompt_output_type_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=["output_type", "result_type", "execution_output_type"],
        )
        prompt_result_parser_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=["result_parser", "parser_strategy", "output_parser", "execution_parser_strategy"],
        )
        prompt_result_formatter_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=["result_formatter", "formatter_strategy", "output_formatter", "execution_formatter_strategy"],
        )
        prompt_output_schema_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=["output_schema", "output_schema_json", "result_schema", "execution_output_schema", "schema_output"],
            default_sql="NULL",
        )
        automation_output_type_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["output_type", "result_type", "execution_output_type"],
        )
        automation_result_parser_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["result_parser", "parser_strategy", "output_parser", "execution_parser_strategy"],
        )
        automation_result_formatter_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["result_formatter", "formatter_strategy", "output_formatter", "execution_formatter_strategy"],
        )
        automation_output_schema_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["output_schema", "output_schema_json", "result_schema", "execution_output_schema", "schema_output"],
            default_sql="NULL",
        )
        prompt_debug_enabled_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=["debug_enabled", "is_debug_enabled", "execution_debug_enabled", "debug_mode"],
            default_sql="NULL::boolean",
        )
        automation_debug_enabled_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["debug_enabled", "is_debug_enabled", "execution_debug_enabled", "debug_mode"],
            default_sql="NULL::boolean",
        )
        automation_slug_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["slug", "automation_slug", "key", "code"],
        )
        is_test_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["is_test", "test_mode", "is_testing", "is_sandbox"],
            default_sql="NULL::boolean",
        )

        runtime_stmt = text(
            f"""
            SELECT
                ap.automation_id,
                {prompt_id_expr} AS prompt_id,
                ap.prompt_text,
                {prompt_active_expr} AS prompt_is_active,
                ap.version AS prompt_version,
                {automation_slug_expr} AS automation_slug,
                {is_test_expr} AS is_test_automation,
                COALESCE(({prompt_provider_id_expr})::text, ({automation_provider_id_expr})::text) AS provider_id,
                COALESCE(({prompt_provider_slug_expr})::text, ({automation_provider_slug_expr})::text) AS provider_slug,
                COALESCE(({prompt_model_id_expr})::text, ({automation_model_id_expr})::text) AS model_id,
                COALESCE(({prompt_model_slug_expr})::text, ({automation_model_slug_expr})::text) AS model_slug,
                COALESCE(({prompt_credential_expr})::text, ({automation_credential_expr})::text) AS credential_id,
                COALESCE({prompt_credential_name_expr}, {automation_credential_name_expr}) AS credential_name,
                COALESCE({prompt_output_type_expr}, {automation_output_type_expr}) AS output_type,
                COALESCE({prompt_result_parser_expr}, {automation_result_parser_expr}) AS result_parser,
                COALESCE({prompt_result_formatter_expr}, {automation_result_formatter_expr}) AS result_formatter,
                COALESCE(({prompt_output_schema_expr})::text, ({automation_output_schema_expr})::text) AS output_schema,
                COALESCE({prompt_debug_enabled_expr}, {automation_debug_enabled_expr}) AS debug_enabled
            FROM automation_prompts ap
            JOIN automations a ON a.id = ap.automation_id
            WHERE ap.automation_id = :automation_id
            ORDER BY ap.version DESC NULLS LAST, ap.created_at DESC NULLS LAST
            LIMIT 1
            """
        )
        row = self.session.execute(runtime_stmt, {"automation_id": str(automation_id)}).mappings().first()
        if row is None:
            return None

        return SharedAutomationRuntimeRecord(
            automation_id=uuid.UUID(str(row["automation_id"])),
            prompt_id=self._coerce_uuid(row.get("prompt_id")),
            prompt_text=str(row["prompt_text"]),
            prompt_is_active=self._coerce_runtime_bool(row.get("prompt_is_active")),
            prompt_version=int(row["prompt_version"]),
            automation_slug=self._clean_runtime_value(row.get("automation_slug")),
            is_test_automation=self._coerce_runtime_bool(row.get("is_test_automation")),
            provider_id=self._coerce_uuid(row.get("provider_id")),
            model_id=self._coerce_uuid(row.get("model_id")),
            provider_slug=self._clean_runtime_value(row.get("provider_slug")),
            model_slug=self._clean_runtime_value(row.get("model_slug")),
            credential_id=self._clean_runtime_value(row.get("credential_id")),
            credential_name=self._clean_runtime_value(row.get("credential_name")),
            output_type=self._clean_runtime_value(row.get("output_type")),
            result_parser=self._clean_runtime_value(row.get("result_parser")),
            result_formatter=self._clean_runtime_value(row.get("result_formatter")),
            output_schema=self._clean_runtime_schema(row.get("output_schema")),
            debug_enabled=self._coerce_runtime_bool(row.get("debug_enabled")),
        )

    def get_runtime_target_for_automation(self, automation_id: uuid.UUID) -> SharedAutomationTargetRecord | None:
        automation_columns = self._get_table_columns("automations")
        slug_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["slug", "automation_slug", "key", "code"],
        )
        is_test_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["is_test", "test_mode", "is_testing", "is_sandbox"],
            default_sql="NULL::boolean",
        )
        provider_id_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=[
                "provider_id",
                "ai_provider_id",
                "llm_provider_id",
            ],
            default_sql="NULL::text",
        )
        provider_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=[
                "provider_slug",
                "provider",
                "ai_provider_slug",
                "ai_provider",
                "llm_provider",
            ],
        )
        model_id_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=[
                "model_id",
                "ai_model_id",
                "llm_model_id",
            ],
            default_sql="NULL::text",
        )
        model_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=[
                "model_slug",
                "model",
                "ai_model_slug",
                "ai_model",
                "llm_model",
            ],
        )
        credential_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["credential_id", "provider_credential_id", "ai_credential_id", "llm_credential_id"],
            default_sql="NULL::text",
        )
        output_type_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["output_type", "result_type", "execution_output_type"],
        )
        result_parser_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["result_parser", "parser_strategy", "output_parser", "execution_parser_strategy"],
        )
        result_formatter_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["result_formatter", "formatter_strategy", "output_formatter", "execution_formatter_strategy"],
        )
        output_schema_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["output_schema", "output_schema_json", "result_schema", "execution_output_schema", "schema_output"],
            default_sql="NULL",
        )
        debug_enabled_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["debug_enabled", "is_debug_enabled", "execution_debug_enabled", "debug_mode"],
            default_sql="NULL::boolean",
        )
        stmt = text(
            f"""
            SELECT
                a.id AS automation_id,
                {slug_expr} AS automation_slug,
                {is_test_expr} AS is_test_automation,
                ({provider_id_expr})::text AS provider_id,
                ({provider_expr})::text AS provider_slug,
                ({model_id_expr})::text AS model_id,
                ({model_expr})::text AS model_slug,
                ({credential_expr})::text AS credential_id,
                {output_type_expr} AS output_type,
                {result_parser_expr} AS result_parser,
                {result_formatter_expr} AS result_formatter,
                ({output_schema_expr})::text AS output_schema,
                {debug_enabled_expr} AS debug_enabled
            FROM automations a
            WHERE a.id = :automation_id
            LIMIT 1
            """
        )
        row = self.session.execute(stmt, {"automation_id": str(automation_id)}).mappings().first()
        if row is None:
            return None
        return SharedAutomationTargetRecord(
            automation_id=uuid.UUID(str(row["automation_id"])),
            automation_slug=self._clean_runtime_value(row.get("automation_slug")),
            is_test_automation=self._coerce_runtime_bool(row.get("is_test_automation")),
            provider_id=self._coerce_uuid(row.get("provider_id")),
            model_id=self._coerce_uuid(row.get("model_id")),
            provider_slug=self._clean_runtime_value(row.get("provider_slug")),
            model_slug=self._clean_runtime_value(row.get("model_slug")),
            credential_id=self._clean_runtime_value(row.get("credential_id")),
            output_type=self._clean_runtime_value(row.get("output_type")),
            result_parser=self._clean_runtime_value(row.get("result_parser")),
            result_formatter=self._clean_runtime_value(row.get("result_formatter")),
            output_schema=self._clean_runtime_schema(row.get("output_schema")),
            debug_enabled=self._coerce_runtime_bool(row.get("debug_enabled")),
        )

    def update_automation_fields(
        self,
        *,
        automation_id: uuid.UUID,
        changes: dict[str, object] | None = None,
    ) -> bool:
        metadata = self._get_table_columns_metadata("automations")
        available_columns = set(metadata.keys())
        if "id" not in available_columns:
            return False

        normalized_changes = dict(changes or {})
        if not normalized_changes:
            return self.get_automation_by_id(automation_id) is not None

        assignments: list[str] = []
        params: dict[str, object] = {"automation_id": str(automation_id)}

        if "name" in normalized_changes and "name" in available_columns:
            params["name"] = str(normalized_changes.get("name") or "").strip()
            assignments.append("name = :name")

        provider_column = self._find_first_available_column(
            available_columns,
            ["provider_id", "ai_provider_id", "llm_provider_id"],
        )
        if "provider_id" in normalized_changes:
            if provider_column is None:
                raise AppException(
                    "Shared automation schema is missing provider field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "provider_id"},
                )
            params["provider_id"] = normalized_changes.get("provider_id")
            assignments.append(f"{provider_column} = :provider_id")

        model_column = self._find_first_available_column(
            available_columns,
            ["model_id", "ai_model_id", "llm_model_id"],
        )
        if "model_id" in normalized_changes:
            if model_column is None:
                raise AppException(
                    "Shared automation schema is missing model field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "model_id"},
                )
            params["model_id"] = normalized_changes.get("model_id")
            assignments.append(f"{model_column} = :model_id")

        credential_column = self._find_first_available_column(
            available_columns,
            ["credential_id", "provider_credential_id", "ai_credential_id", "llm_credential_id"],
        )
        if "credential_id" in normalized_changes:
            if credential_column is None:
                raise AppException(
                    "Shared automation schema is missing credential field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "credential_id"},
                )
            params["credential_id"] = normalized_changes.get("credential_id")
            assignments.append(f"{credential_column} = :credential_id")

        output_type_column = self._find_first_available_column(
            available_columns,
            ["output_type", "result_type", "execution_output_type"],
        )
        if "output_type" in normalized_changes:
            if output_type_column is None:
                raise AppException(
                    "Shared automation schema is missing output_type field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "output_type"},
                )
            raw_output_type = normalized_changes.get("output_type")
            params["output_type"] = None if raw_output_type is None else str(raw_output_type).strip()
            assignments.append(f"{output_type_column} = :output_type")

        result_parser_column = self._find_first_available_column(
            available_columns,
            ["result_parser", "parser_strategy", "output_parser", "execution_parser_strategy"],
        )
        if "result_parser" in normalized_changes:
            if result_parser_column is None:
                raise AppException(
                    "Shared automation schema is missing result_parser field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "result_parser"},
                )
            raw_result_parser = normalized_changes.get("result_parser")
            params["result_parser"] = None if raw_result_parser is None else str(raw_result_parser).strip()
            assignments.append(f"{result_parser_column} = :result_parser")

        result_formatter_column = self._find_first_available_column(
            available_columns,
            ["result_formatter", "formatter_strategy", "output_formatter", "execution_formatter_strategy"],
        )
        if "result_formatter" in normalized_changes:
            if result_formatter_column is None:
                raise AppException(
                    "Shared automation schema is missing result_formatter field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "result_formatter"},
                )
            raw_result_formatter = normalized_changes.get("result_formatter")
            params["result_formatter"] = None if raw_result_formatter is None else str(raw_result_formatter).strip()
            assignments.append(f"{result_formatter_column} = :result_formatter")

        output_schema_column = self._find_first_available_column(
            available_columns,
            ["output_schema", "output_schema_json", "result_schema", "execution_output_schema", "schema_output"],
        )
        if "output_schema" in normalized_changes:
            if output_schema_column is None:
                raise AppException(
                    "Shared automation schema is missing output_schema field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "output_schema"},
                )
            params["output_schema"] = self._coerce_output_schema_for_column(
                output_schema=normalized_changes.get("output_schema"),
                column_meta=metadata.get(output_schema_column),
            )
            assignments.append(f"{output_schema_column} = :output_schema")

        if "updated_at" in available_columns:
            params["updated_at"] = datetime.now(timezone.utc)
            assignments.append("updated_at = :updated_at")

        if not assignments:
            return self.get_automation_by_id(automation_id) is not None

        stmt = text(
            f"""
            UPDATE automations
            SET {", ".join(assignments)}
            WHERE id = :automation_id
            """
        )
        result = self.session.execute(stmt, params)
        return int(result.rowcount or 0) > 0

    def set_automation_status(self, *, automation_id: uuid.UUID, is_active: bool) -> bool:
        automation_columns = self._get_table_columns("automations")
        active_column = self._find_active_column(automation_columns)
        if active_column is None:
            raise AppException(
                "Automation status field is unavailable in shared schema.",
                status_code=500,
                code="status_field_unavailable",
                details={"table": "automations"},
            )

        params: dict[str, object] = {
            "automation_id": str(automation_id),
            "is_active": bool(is_active),
        }
        assignments = [f"{active_column} = :is_active"]
        if "updated_at" in automation_columns:
            params["updated_at"] = datetime.now(timezone.utc)
            assignments.append("updated_at = :updated_at")

        stmt = text(
            f"""
            UPDATE automations
            SET {", ".join(assignments)}
            WHERE id = :automation_id
            """
        )
        result = self.session.execute(stmt, params)
        return int(result.rowcount or 0) > 0

    def upsert_latest_prompt_for_automation(
        self,
        *,
        automation_id: uuid.UUID,
        prompt_text: str,
        is_active: bool = True,
    ) -> bool:
        prompt_metadata = self._get_table_columns_metadata("automation_prompts")
        prompt_columns = set(prompt_metadata.keys())
        if "id" not in prompt_columns or "automation_id" not in prompt_columns or "prompt_text" not in prompt_columns:
            raise AppException(
                "Shared prompt schema is not compatible with prompt updates.",
                status_code=500,
                code="prompt_schema_incompatible",
            )

        order_terms: list[str] = []
        if "version" in prompt_columns:
            order_terms.append("ap.version DESC NULLS LAST")
        if "created_at" in prompt_columns:
            order_terms.append("ap.created_at DESC NULLS LAST")
        order_terms.append("ap.id DESC")
        latest_stmt = text(
            f"""
            SELECT ap.id
            FROM automation_prompts ap
            WHERE ap.automation_id = :automation_id
            ORDER BY {", ".join(order_terms)}
            LIMIT 1
            """
        )
        latest_row = self.session.execute(latest_stmt, {"automation_id": str(automation_id)}).mappings().first()
        latest_prompt_id = self._coerce_uuid(latest_row.get("id")) if latest_row else None

        if latest_prompt_id is not None:
            assignments = ["prompt_text = :prompt_text"]
            params: dict[str, object] = {
                "prompt_id": str(latest_prompt_id),
                "prompt_text": str(prompt_text).strip(),
            }
            active_column = self._find_active_column(prompt_columns)
            if active_column is not None:
                assignments.append(f"{active_column} = :is_active")
                params["is_active"] = bool(is_active)
            if "updated_at" in prompt_columns:
                assignments.append("updated_at = :updated_at")
                params["updated_at"] = datetime.now(timezone.utc)
            stmt = text(
                f"""
                UPDATE automation_prompts
                SET {", ".join(assignments)}
                WHERE id = :prompt_id
                """
            )
            result = self.session.execute(stmt, params)
            return int(result.rowcount or 0) > 0

        now = datetime.now(timezone.utc)
        prompt_id = uuid.uuid4()
        values: dict[str, object] = {
            "id": prompt_id,
            "automation_id": automation_id,
            "prompt_text": str(prompt_text).strip(),
        }
        active_column = self._find_active_column(prompt_columns)
        if active_column is not None:
            values[active_column] = bool(is_active)
        if "version" in prompt_columns:
            values["version"] = 1
        if "created_at" in prompt_columns:
            values["created_at"] = now
        if "updated_at" in prompt_columns:
            values["updated_at"] = now
        if "owner_token_id" in prompt_columns:
            owner_token_stmt = text(
                """
                SELECT a.owner_token_id
                FROM automations a
                WHERE a.id = :automation_id
                LIMIT 1
                """
            )
            owner_token_id = self.session.execute(owner_token_stmt, {"automation_id": str(automation_id)}).scalar()
            values["owner_token_id"] = owner_token_id

        required_columns = self._required_columns_without_default(prompt_metadata)
        for column_name in sorted(required_columns):
            if column_name in values:
                continue
            guessed = self._guess_required_prompt_value(
                column_name=column_name,
                column_meta=prompt_metadata[column_name],
                prompt_id=prompt_id,
                automation_id=automation_id,
                prompt_text=str(prompt_text).strip(),
                now=now,
                is_active=is_active,
            )
            if guessed is None:
                raise AppException(
                    "Prompt schema has unsupported required columns for this operation.",
                    status_code=500,
                    code="prompt_schema_incompatible",
                    details={"missing_column": column_name},
                )
            values[column_name] = guessed

        columns = list(values.keys())
        insert_stmt = text(
            f"""
            INSERT INTO automation_prompts ({", ".join(columns)})
            VALUES ({", ".join(f":{column}" for column in columns)})
            """
        )
        self.session.execute(insert_stmt, values)
        return True

    def delete_prompts_for_automation(self, *, automation_id: uuid.UUID) -> int:
        prompt_columns = self._get_table_columns("automation_prompts")
        if "automation_id" not in prompt_columns:
            return 0
        stmt = text(
            """
            DELETE FROM automation_prompts
            WHERE automation_id = :automation_id
            """
        )
        result = self.session.execute(stmt, {"automation_id": str(automation_id)})
        return int(result.rowcount or 0)

    def count_prompts_for_automation(self, *, automation_id: uuid.UUID) -> int:
        prompt_columns = self._get_table_columns("automation_prompts")
        if "automation_id" not in prompt_columns:
            return 0
        stmt = text(
            """
            SELECT COUNT(1)
            FROM automation_prompts
            WHERE automation_id = :automation_id
            """
        )
        value = self.session.execute(stmt, {"automation_id": str(automation_id)}).scalar()
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def delete_automation_by_id(self, *, automation_id: uuid.UUID) -> bool:
        automation_columns = self._get_table_columns("automations")
        if "id" not in automation_columns:
            return False
        stmt = text(
            """
            DELETE FROM automations
            WHERE id = :automation_id
            """
        )
        result = self.session.execute(stmt, {"automation_id": str(automation_id)})
        return int(result.rowcount or 0) > 0

    def _get_table_columns(self, table_name: str) -> set[str]:
        stmt = text(
            """
            SELECT c.column_name
            FROM information_schema.columns c
            WHERE c.table_schema = current_schema()
              AND c.table_name = :table_name
            """
        )
        rows = self.session.execute(stmt, {"table_name": table_name}).scalars().all()
        return {str(column_name) for column_name in rows}

    def _get_table_columns_metadata(self, table_name: str) -> dict[str, dict[str, object]]:
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
        rows = self.session.execute(stmt, {"table_name": table_name}).mappings().all()
        return {
            str(row["column_name"]): {
                "is_nullable": row.get("is_nullable"),
                "column_default": row.get("column_default"),
                "data_type": row.get("data_type"),
                "udt_name": row.get("udt_name"),
            }
            for row in rows
        }

    def _create_technical_automation(
        self,
        *,
        automation_id: uuid.UUID,
        slug: str,
        name: str,
        metadata: dict[str, dict[str, object]],
    ) -> SharedAutomationRecord:
        now = datetime.now(timezone.utc)
        values = self._build_technical_automation_values(
            automation_id=automation_id,
            slug=slug,
            name=name,
            metadata=metadata,
            now=now,
        )
        column_names = list(values.keys())
        insert_stmt = text(
            f"""
            INSERT INTO automations ({", ".join(column_names)})
            VALUES ({", ".join(f":{column_name}" for column_name in column_names)})
            """
        )
        try:
            self.session.execute(insert_stmt, values)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            logger.exception(
                "Failed to create technical shared automation for prompt tests.",
                extra={
                    "automation_id": str(automation_id),
                    "automation_slug": slug,
                    "columns": sorted(column_names),
                },
                exc_info=exc,
            )
            raise AppException(
                "Failed to auto-create technical shared automation for prompt tests.",
                status_code=500,
                code="test_prompt_runtime_shared_automation_create_failed",
                details={"table": "automations", "error": str(exc)},
            ) from exc

        created = self.get_automation_by_id(automation_id)
        if created is None:
            raise AppException(
                "Technical shared automation was created but could not be read back.",
                status_code=500,
                code="test_prompt_runtime_invalid",
                details={"automation_id": str(automation_id)},
            )
        return created

    def _normalize_technical_automation(
        self,
        *,
        automation_id: uuid.UUID,
        slug: str,
        name: str,
        metadata: dict[str, dict[str, object]],
    ) -> SharedAutomationRecord:
        values: dict[str, object] = {"automation_id": str(automation_id)}
        assignments: list[str] = []
        now = datetime.now(timezone.utc)

        if "name" in metadata:
            values["name"] = name
            assignments.append("name = :name")

        slug_column = self._find_slug_column(set(metadata.keys()))
        if slug_column is not None:
            values[slug_column] = slug
            assignments.append(f"{slug_column} = :{slug_column}")

        active_column = self._find_active_column(set(metadata.keys()))
        if active_column is not None:
            values[active_column] = True
            assignments.append(f"{active_column} = :{active_column}")

        test_marker_column = self._find_test_marker_column(set(metadata.keys()))
        if test_marker_column is not None:
            values[test_marker_column] = True
            assignments.append(f"{test_marker_column} = :{test_marker_column}")

        if "updated_at" in metadata:
            values["updated_at"] = now
            assignments.append("updated_at = :updated_at")

        if assignments:
            stmt = text(
                f"""
                UPDATE automations
                SET {", ".join(assignments)}
                WHERE id = :automation_id
                """
            )
            try:
                self.session.execute(stmt, values)
                self.session.commit()
            except Exception as exc:
                self.session.rollback()
                logger.exception(
                    "Failed to normalize technical shared automation for prompt tests.",
                    extra={
                        "automation_id": str(automation_id),
                        "automation_slug": slug,
                        "columns": sorted(assignments),
                    },
                    exc_info=exc,
                )
                raise AppException(
                    "Failed to normalize technical shared automation for prompt tests.",
                    status_code=500,
                    code="test_prompt_runtime_shared_automation_update_failed",
                    details={"table": "automations", "error": str(exc)},
                ) from exc

        refreshed = self.get_automation_by_id(automation_id)
        if refreshed is None:
            raise AppException(
                "Technical shared automation could not be confirmed after normalization.",
                status_code=500,
                code="test_prompt_runtime_invalid",
                details={"automation_id": str(automation_id)},
            )
        return refreshed

    def _build_technical_automation_values(
        self,
        *,
        automation_id: uuid.UUID,
        slug: str,
        name: str,
        metadata: dict[str, dict[str, object]],
        now: datetime,
    ) -> dict[str, object]:
        values: dict[str, object] = {}
        if "id" in metadata:
            values["id"] = automation_id
        if "name" in metadata:
            values["name"] = name

        slug_column = self._find_slug_column(set(metadata.keys()))
        if slug_column is not None:
            values[slug_column] = slug

        active_column = self._find_active_column(set(metadata.keys()))
        if active_column is not None:
            values[active_column] = True

        test_marker_column = self._find_test_marker_column(set(metadata.keys()))
        if test_marker_column is not None:
            values[test_marker_column] = True

        if "created_at" in metadata:
            values["created_at"] = now
        if "updated_at" in metadata:
            values["updated_at"] = now

        required_columns = self._required_columns_without_default(metadata)
        for column_name in sorted(required_columns):
            if column_name in values:
                continue
            guessed = self._guess_required_automation_value(
                column_name=column_name,
                column_meta=metadata[column_name],
                automation_id=automation_id,
                name=name,
                slug=slug,
                now=now,
            )
            if guessed is None:
                raise AppException(
                    "Unable to auto-create technical shared automation due to shared schema requirements.",
                    status_code=500,
                    code="test_prompt_runtime_shared_automation_schema_incompatible",
                    details={"missing_column": column_name},
                )
            values[column_name] = guessed
        return values

    @staticmethod
    def _required_columns_without_default(columns: dict[str, dict[str, object]]) -> set[str]:
        required: set[str] = set()
        for column_name, meta in columns.items():
            if str(meta.get("is_nullable") or "").upper() == "YES":
                continue
            if meta.get("column_default") is not None:
                continue
            required.add(column_name)
        return required

    @staticmethod
    def _guess_required_automation_value(
        *,
        column_name: str,
        column_meta: dict[str, object],
        automation_id: uuid.UUID,
        name: str,
        slug: str,
        now: datetime,
    ) -> object | None:
        lower_name = str(column_name or "").strip().lower()
        data_type = str(column_meta.get("data_type") or "").strip().lower()
        udt_name = str(column_meta.get("udt_name") or "").strip().lower()
        merged_type = f"{data_type} {udt_name}".strip()

        if lower_name == "id":
            return automation_id
        if lower_name == "name" or lower_name.endswith("_name"):
            return name
        if lower_name in {"slug", "automation_slug", "key", "code"} or lower_name.endswith("_slug"):
            return slug
        if "provider" in lower_name or "model" in lower_name:
            return None
        if lower_name == "description":
            return "Automacao tecnica oficial para runtime de prompts de teste."
        if lower_name in {"status", "state"}:
            return "active"
        if lower_name in {"source", "origin"}:
            return "prompt_test_runtime"
        if lower_name in {"type", "kind", "category"}:
            return "prompt_test_runtime"
        if lower_name in {"is_active", "active", "enabled", "is_test", "test_mode", "is_testing", "is_sandbox"}:
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
            if "slug" in lower_name or lower_name in {"key", "code"}:
                return slug
            if "name" in lower_name:
                return name
            return "prompt_test_runtime"
        if any(token in merged_type for token in ["timestamp", "date", "time"]):
            return now
        return None

    @staticmethod
    def _guess_required_prompt_value(
        *,
        column_name: str,
        column_meta: dict[str, object],
        prompt_id: uuid.UUID,
        automation_id: uuid.UUID,
        prompt_text: str,
        now: datetime,
        is_active: bool,
    ) -> object | None:
        lower_name = str(column_name or "").strip().lower()
        data_type = str(column_meta.get("data_type") or "").strip().lower()
        udt_name = str(column_meta.get("udt_name") or "").strip().lower()
        merged_type = f"{data_type} {udt_name}".strip()

        if lower_name == "id":
            return prompt_id
        if lower_name == "automation_id":
            return automation_id
        if lower_name == "prompt_text":
            return prompt_text
        if lower_name in {"version"}:
            return 1
        if lower_name in {"is_active", "active", "enabled"}:
            return bool(is_active)
        if lower_name in {"created_at", "updated_at"} or lower_name.endswith("_at"):
            return now

        if "uuid" in merged_type:
            return None
        if "bool" in merged_type:
            return bool(is_active)
        if any(token in merged_type for token in ["int", "numeric", "decimal", "double", "real"]):
            return 1
        if "json" in merged_type:
            return {}
        if any(token in merged_type for token in ["char", "text", "varchar"]):
            return ""
        if any(token in merged_type for token in ["timestamp", "date", "time"]):
            return now
        return None

    @staticmethod
    def _find_first_available_column(available_columns: set[str], candidates: list[str]) -> str | None:
        for candidate in candidates:
            if candidate in available_columns:
                return candidate
        return None

    @staticmethod
    def _coerce_output_schema_for_column(
        *,
        output_schema: object | None,
        column_meta: dict[str, object] | None,
    ) -> object | None:
        if output_schema is None:
            return None

        data_type = str((column_meta or {}).get("data_type") or "").strip().lower()
        udt_name = str((column_meta or {}).get("udt_name") or "").strip().lower()
        merged_type = f"{data_type} {udt_name}".strip()
        is_json_column = "json" in merged_type

        if isinstance(output_schema, dict):
            if is_json_column:
                return output_schema
            return json.dumps(output_schema, ensure_ascii=False)

        if isinstance(output_schema, str):
            normalized = output_schema.strip()
            if not normalized:
                return None
            if is_json_column:
                try:
                    return json.loads(normalized)
                except json.JSONDecodeError as exc:
                    raise AppException(
                        "Output schema is invalid: expected a JSON object.",
                        status_code=422,
                        code="execution_output_schema_invalid",
                    ) from exc
            return normalized

        raise AppException(
            "Output schema is invalid: expected a JSON object.",
            status_code=422,
            code="execution_output_schema_invalid",
        )

    @staticmethod
    def _find_slug_column(available_columns: set[str]) -> str | None:
        for candidate in ["slug", "automation_slug", "key", "code"]:
            if candidate in available_columns:
                return candidate
        return None

    @staticmethod
    def _find_active_column(available_columns: set[str]) -> str | None:
        for candidate in ["is_active", "active", "enabled"]:
            if candidate in available_columns:
                return candidate
        return None

    @staticmethod
    def _find_test_marker_column(available_columns: set[str]) -> str | None:
        for candidate in ["is_test", "test_mode", "is_testing", "is_sandbox"]:
            if candidate in available_columns:
                return candidate
        return None

    @staticmethod
    def _build_automation_select_sql(*, table_alias: str, available_columns: set[str]) -> str:
        name_expr = f"{table_alias}.name" if "name" in available_columns else f"{table_alias}.id::text"
        active_expr = (
            f"{table_alias}.is_active"
            if "is_active" in available_columns
            else "TRUE"
        )
        owner_token_expr = (
            f"{table_alias}.owner_token_id"
            if "owner_token_id" in available_columns
            else "NULL::uuid"
        )
        return (
            f"{table_alias}.id AS id, "
            f"{name_expr} AS name, "
            f"{active_expr} AS is_active, "
            f"{owner_token_expr} AS owner_token_id"
        )

    @staticmethod
    def _merge_default_active_row(
        row: object | None,
        *,
        available_columns: set[str],
    ) -> dict[str, object] | None:
        if row is None:
            return None
        payload = dict(row)
        if "is_active" not in available_columns:
            payload["is_active"] = True
        return payload

    def _build_automation_record(
        self,
        row: object | None,
        *,
        available_columns: set[str],
    ) -> SharedAutomationRecord | None:
        payload = self._merge_default_active_row(
            row,
            available_columns=available_columns,
        )
        if payload is None:
            return None
        automation_id = self._coerce_uuid(payload.get("id"))
        if automation_id is None:
            return None
        return SharedAutomationRecord(
            id=automation_id,
            name=str(payload.get("name") or "").strip() or str(automation_id),
            is_active=self._coerce_runtime_bool(payload.get("is_active")) is not False,
            owner_token_id=self._coerce_uuid(payload.get("owner_token_id")),
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
    def _build_runtime_expr(
        *,
        table_alias: str,
        available_columns: set[str],
        candidates: list[str],
        default_sql: str = "NULL::text",
    ) -> tuple[str, str | None]:
        for candidate in candidates:
            if candidate in available_columns:
                return f"{table_alias}.{candidate}", candidate
        return default_sql, None

    @staticmethod
    def _clean_runtime_value(value: object | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _clean_runtime_schema(value: object | None) -> dict[str, Any] | str | None:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _coerce_runtime_bool(value: object | None) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "t", "yes", "y"}:
            return True
        if normalized in {"0", "false", "f", "no", "n"}:
            return False
        return None
