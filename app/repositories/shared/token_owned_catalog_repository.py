from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import uuid

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.orm import Session

from app.core.exceptions import AppException


@dataclass(slots=True)
class TokenOwnedAutomationRecord:
    id: uuid.UUID
    name: str
    provider_id: uuid.UUID | None
    model_id: uuid.UUID | None
    credential_id: uuid.UUID | None
    output_type: str | None
    result_parser: str | None
    result_formatter: str | None
    output_schema: dict[str, object] | None
    is_active: bool
    owner_token_id: uuid.UUID | None


@dataclass(slots=True)
class TokenOwnedPromptRecord:
    id: uuid.UUID
    automation_id: uuid.UUID
    prompt_text: str
    version: int
    created_at: datetime
    is_active: bool
    owner_token_id: uuid.UUID | None


class TokenOwnedCatalogRepository:
    """
    Shared catalog repository scoped by external API token ownership.

    This repository is intentionally explicit about ownership filters so future
    update/delete/toggle operations can reuse the same resolution methods.
    """

    OWNER_COLUMN = "owner_token_id"
    ACTIVE_CANDIDATES = ("is_active", "active", "enabled")
    PROVIDER_CANDIDATES = ("provider_id", "ai_provider_id", "llm_provider_id")
    MODEL_CANDIDATES = ("model_id", "ai_model_id", "llm_model_id")
    CREDENTIAL_CANDIDATES = ("credential_id", "provider_credential_id", "ai_credential_id", "llm_credential_id")
    OUTPUT_TYPE_CANDIDATES = ("output_type", "result_type", "execution_output_type")
    RESULT_PARSER_CANDIDATES = ("result_parser", "parser_strategy", "output_parser", "execution_parser_strategy")
    RESULT_FORMATTER_CANDIDATES = ("result_formatter", "formatter_strategy", "output_formatter", "execution_formatter_strategy")
    OUTPUT_SCHEMA_CANDIDATES = (
        "output_schema",
        "output_schema_json",
        "result_schema",
        "execution_output_schema",
        "schema_output",
    )

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_automations_by_token(
        self,
        *,
        token_id: uuid.UUID,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[TokenOwnedAutomationRecord]:
        automation_columns = self._get_table_columns("automations")
        self._ensure_owner_column(table_name="automations", columns=automation_columns)
        if "id" not in automation_columns or "name" not in automation_columns:
            return []

        _, active_column = self._build_active_expr(
            table_alias="a",
            available_columns=automation_columns,
        )
        where_clauses = [f"a.{self.OWNER_COLUMN} = :token_id"]
        params: dict[str, object] = {"token_id": token_id}
        if is_active is not None:
            if active_column is None:
                if not is_active:
                    return []
            else:
                where_clauses.append(f"a.{active_column} = :is_active")
                params["is_active"] = bool(is_active)

        pagination_sql = self._build_pagination_sql(limit=limit, offset=offset, params=params)
        stmt = text(
            f"""
            SELECT {self._build_automation_select_sql(table_alias="a", available_columns=automation_columns)}
            FROM automations a
            WHERE {" AND ".join(where_clauses)}
            ORDER BY a.name ASC, a.id ASC
            {pagination_sql}
            """
        )
        rows = self.session.execute(stmt, params).mappings().all()
        items: list[TokenOwnedAutomationRecord] = []
        for row in rows:
            item = self._build_automation_record(row)
            if item is not None:
                items.append(item)
        return items

    def get_automation_by_id_and_token(
        self,
        *,
        automation_id: uuid.UUID,
        token_id: uuid.UUID,
    ) -> TokenOwnedAutomationRecord | None:
        automation_columns = self._get_table_columns("automations")
        self._ensure_owner_column(table_name="automations", columns=automation_columns)
        if "id" not in automation_columns or "name" not in automation_columns:
            return None

        stmt = text(
            f"""
            SELECT {self._build_automation_select_sql(table_alias="a", available_columns=automation_columns)}
            FROM automations a
            WHERE a.id = :automation_id
              AND a.{self.OWNER_COLUMN} = :token_id
            LIMIT 1
            """
        )
        row = self.session.execute(
            stmt,
            {"automation_id": automation_id, "token_id": token_id},
        ).mappings().first()
        return self._build_automation_record(row)

    def get_automation_by_id(self, *, automation_id: uuid.UUID) -> TokenOwnedAutomationRecord | None:
        automation_columns = self._get_table_columns("automations")
        if "id" not in automation_columns or "name" not in automation_columns:
            return None

        stmt = text(
            f"""
            SELECT {self._build_automation_select_sql(table_alias="a", available_columns=automation_columns)}
            FROM automations a
            WHERE a.id = :automation_id
            LIMIT 1
            """
        )
        row = self.session.execute(stmt, {"automation_id": automation_id}).mappings().first()
        return self._build_automation_record(row)

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
        output_schema: dict[str, object] | None = None,
        is_active: bool = True,
    ) -> TokenOwnedAutomationRecord:
        metadata = self._get_table_columns_metadata("automations")
        automation_columns = set(metadata.keys())
        self._ensure_owner_column(table_name="automations", columns=automation_columns)
        if "id" not in metadata or "name" not in metadata:
            raise AppException(
                "Shared table 'automations' is not compatible with external catalog writes.",
                status_code=500,
                code="automation_schema_incompatible",
            )

        provider_column = self._find_first_available_column(automation_columns, self.PROVIDER_CANDIDATES)
        model_column = self._find_first_available_column(automation_columns, self.MODEL_CANDIDATES)
        credential_column = self._find_first_available_column(automation_columns, self.CREDENTIAL_CANDIDATES)
        output_type_column = self._find_first_available_column(automation_columns, self.OUTPUT_TYPE_CANDIDATES)
        result_parser_column = self._find_first_available_column(automation_columns, self.RESULT_PARSER_CANDIDATES)
        result_formatter_column = self._find_first_available_column(automation_columns, self.RESULT_FORMATTER_CANDIDATES)
        output_schema_column = self._find_first_available_column(automation_columns, self.OUTPUT_SCHEMA_CANDIDATES)
        if provider_column is None or model_column is None:
            missing = "provider_id" if provider_column is None else "model_id"
            raise AppException(
                "Shared automation schema is missing required runtime catalog fields.",
                status_code=500,
                code="automation_schema_incompatible",
                details={"missing_column": missing},
            )

        now = datetime.now(timezone.utc)
        automation_id = uuid.uuid4()
        values: dict[str, object] = {
            "id": automation_id,
            "name": str(name or "").strip(),
            self.OWNER_COLUMN: token_id,
            provider_column: provider_id,
            model_column: model_id,
        }
        if credential_column is not None:
            values[credential_column] = credential_id
        if output_type_column is not None and output_type is not None:
            values[output_type_column] = str(output_type).strip()
        if result_parser_column is not None and result_parser is not None:
            values[result_parser_column] = str(result_parser).strip()
        if result_formatter_column is not None and result_formatter is not None:
            values[result_formatter_column] = str(result_formatter).strip()
        if output_schema_column is not None and output_schema is not None:
            values[output_schema_column] = self._coerce_output_schema_for_column(
                output_schema=output_schema,
                column_meta=metadata.get(output_schema_column),
            )
        active_column = self._find_active_column(set(metadata.keys()))
        if active_column is not None:
            values[active_column] = bool(is_active)
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
                column_meta=metadata.get(column_name),
                automation_id=automation_id,
                name=str(name or "").strip(),
                token_id=token_id,
                provider_id=provider_id,
                model_id=model_id,
                credential_id=credential_id,
                output_type=output_type,
                result_parser=result_parser,
                result_formatter=result_formatter,
                output_schema=output_schema,
                is_active=is_active,
                now=now,
            )
            if guessed is None:
                raise AppException(
                    "Automation schema has unsupported required columns for this external operation.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": column_name},
                )
            values[column_name] = guessed

        columns = list(values.keys())
        insert_stmt = text(
            f"""
            INSERT INTO automations ({", ".join(columns)})
            VALUES ({", ".join(f":{column}" for column in columns)})
            """
        )
        insert_stmt = self._apply_json_typed_bindparams(
            stmt=insert_stmt,
            params=values,
            param_to_column={column_name: column_name for column_name in columns},
            metadata=metadata,
        )
        self.session.execute(insert_stmt, values)

        created = self.get_automation_by_id_and_token(automation_id=automation_id, token_id=token_id)
        if created is None:
            raise AppException(
                "Automation created but not visible in current token scope.",
                status_code=500,
                code="automation_create_inconsistent",
                details={"automation_id": str(automation_id)},
            )
        return created

    def update_automation(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
        changes: dict[str, object] | None = None,
    ) -> TokenOwnedAutomationRecord | None:
        metadata = self._get_table_columns_metadata("automations")
        automation_columns = set(metadata.keys())
        self._ensure_owner_column(table_name="automations", columns=automation_columns)
        if "id" not in automation_columns:
            return None
        changes = dict(changes or {})
        if not changes:
            return self.get_automation_by_id_and_token(
                automation_id=automation_id,
                token_id=token_id,
            )

        assignments: list[str] = []
        params: dict[str, object] = {
            "automation_id": automation_id,
            "token_id": token_id,
        }
        if "name" in changes and "name" in automation_columns:
            params["name"] = str(changes.get("name") or "").strip()
            assignments.append("name = :name")
        provider_column = self._find_first_available_column(automation_columns, self.PROVIDER_CANDIDATES)
        if "provider_id" in changes:
            if provider_column is None:
                raise AppException(
                    "Shared automation schema is missing provider field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "provider_id"},
                )
            params["provider_id"] = changes.get("provider_id")
            assignments.append(f"{provider_column} = :provider_id")
        model_column = self._find_first_available_column(automation_columns, self.MODEL_CANDIDATES)
        if "model_id" in changes:
            if model_column is None:
                raise AppException(
                    "Shared automation schema is missing model field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "model_id"},
                )
            params["model_id"] = changes.get("model_id")
            assignments.append(f"{model_column} = :model_id")
        credential_column = self._find_first_available_column(automation_columns, self.CREDENTIAL_CANDIDATES)
        if "credential_id" in changes:
            if credential_column is None:
                raise AppException(
                    "Shared automation schema is missing credential field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "credential_id"},
                )
            params["credential_id"] = changes.get("credential_id")
            assignments.append(f"{credential_column} = :credential_id")
        output_type_column = self._find_first_available_column(automation_columns, self.OUTPUT_TYPE_CANDIDATES)
        if "output_type" in changes:
            if output_type_column is None:
                raise AppException(
                    "Shared automation schema is missing output_type field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "output_type"},
                )
            raw_output_type = changes.get("output_type")
            params["output_type"] = None if raw_output_type is None else str(raw_output_type).strip()
            assignments.append(f"{output_type_column} = :output_type")
        result_parser_column = self._find_first_available_column(automation_columns, self.RESULT_PARSER_CANDIDATES)
        if "result_parser" in changes:
            if result_parser_column is None:
                raise AppException(
                    "Shared automation schema is missing result_parser field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "result_parser"},
                )
            raw_result_parser = changes.get("result_parser")
            params["result_parser"] = None if raw_result_parser is None else str(raw_result_parser).strip()
            assignments.append(f"{result_parser_column} = :result_parser")
        result_formatter_column = self._find_first_available_column(automation_columns, self.RESULT_FORMATTER_CANDIDATES)
        if "result_formatter" in changes:
            if result_formatter_column is None:
                raise AppException(
                    "Shared automation schema is missing result_formatter field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "result_formatter"},
                )
            raw_result_formatter = changes.get("result_formatter")
            params["result_formatter"] = None if raw_result_formatter is None else str(raw_result_formatter).strip()
            assignments.append(f"{result_formatter_column} = :result_formatter")
        output_schema_column = self._find_first_available_column(automation_columns, self.OUTPUT_SCHEMA_CANDIDATES)
        if "output_schema" in changes:
            if output_schema_column is None:
                raise AppException(
                    "Shared automation schema is missing output_schema field.",
                    status_code=500,
                    code="automation_schema_incompatible",
                    details={"missing_column": "output_schema"},
                )
            raw_output_schema = changes.get("output_schema")
            params["output_schema"] = (
                None
                if raw_output_schema is None
                else self._coerce_output_schema_for_column(
                    output_schema=raw_output_schema,
                    column_meta=metadata.get(output_schema_column),
                )
            )
            assignments.append(f"{output_schema_column} = :output_schema")
        active_column = self._find_active_column(automation_columns)
        if "is_active" in changes:
            if active_column is None:
                raise AppException(
                    "Automation status field is unavailable in shared schema.",
                    status_code=500,
                    code="status_field_unavailable",
                    details={"table": "automations"},
                )
            params["is_active"] = bool(changes.get("is_active"))
            assignments.append(f"{active_column} = :is_active")
        if "updated_at" in automation_columns:
            params["updated_at"] = datetime.now(timezone.utc)
            assignments.append("updated_at = :updated_at")
        if not assignments:
            return self.get_automation_by_id_and_token(
                automation_id=automation_id,
                token_id=token_id,
            )

        stmt = text(
            f"""
            UPDATE automations
            SET {", ".join(assignments)}
            WHERE id = :automation_id
              AND {self.OWNER_COLUMN} = :token_id
            """
        )
        stmt = self._apply_json_typed_bindparams(
            stmt=stmt,
            params=params,
            param_to_column=(
                {"output_schema": output_schema_column}
                if output_schema_column is not None and "output_schema" in params
                else {}
            ),
            metadata=metadata,
        )
        result = self.session.execute(stmt, params)
        if int(result.rowcount or 0) <= 0:
            return None
        return self.get_automation_by_id_and_token(
            automation_id=automation_id,
            token_id=token_id,
        )

    def set_automation_status(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
        is_active: bool,
    ) -> TokenOwnedAutomationRecord | None:
        automation_columns = self._get_table_columns("automations")
        self._ensure_owner_column(table_name="automations", columns=automation_columns)
        active_column = self._find_active_column(automation_columns)
        if active_column is None:
            raise AppException(
                "Automation status field is unavailable in shared schema.",
                status_code=500,
                code="status_field_unavailable",
                details={"table": "automations"},
            )

        params: dict[str, object] = {
            "automation_id": automation_id,
            "token_id": token_id,
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
              AND {self.OWNER_COLUMN} = :token_id
            """
        )
        result = self.session.execute(stmt, params)
        if int(result.rowcount or 0) <= 0:
            return None
        return self.get_automation_by_id_and_token(
            automation_id=automation_id,
            token_id=token_id,
        )

    def delete_automation_by_id_and_token(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
    ) -> bool:
        automation_columns = self._get_table_columns("automations")
        self._ensure_owner_column(table_name="automations", columns=automation_columns)
        stmt = text(
            f"""
            DELETE FROM automations
            WHERE id = :automation_id
              AND {self.OWNER_COLUMN} = :token_id
            """
        )
        result = self.session.execute(
            stmt,
            {"automation_id": automation_id, "token_id": token_id},
        )
        return int(result.rowcount or 0) > 0

    def count_prompts_for_automation(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
    ) -> int:
        prompt_columns = self._get_table_columns("automation_prompts")
        self._ensure_owner_column(table_name="automation_prompts", columns=prompt_columns)
        if "automation_id" not in prompt_columns:
            return 0
        stmt = text(
            f"""
            SELECT COUNT(1)
            FROM automation_prompts ap
            WHERE ap.automation_id = :automation_id
              AND ap.{self.OWNER_COLUMN} = :token_id
            """
        )
        value = self.session.execute(
            stmt,
            {"automation_id": automation_id, "token_id": token_id},
        ).scalar()
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def list_prompts_by_token(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[TokenOwnedPromptRecord]:
        prompt_columns = self._get_table_columns("automation_prompts")
        automation_columns = self._get_table_columns("automations")
        self._ensure_owner_column(table_name="automation_prompts", columns=prompt_columns)
        self._ensure_owner_column(table_name="automations", columns=automation_columns)
        if "id" not in prompt_columns or "automation_id" not in prompt_columns or "prompt_text" not in prompt_columns:
            return []

        version_expr = "ap.version" if "version" in prompt_columns else "1"
        created_expr = "ap.created_at" if "created_at" in prompt_columns else "now()"
        active_expr, active_column = self._build_active_expr(
            table_alias="ap",
            available_columns=prompt_columns,
        )
        order_terms: list[str] = []
        if "created_at" in prompt_columns:
            order_terms.append("ap.created_at DESC")
        if "version" in prompt_columns:
            order_terms.append("ap.version DESC")
        order_terms.append("ap.id DESC")
        where_clauses = [
            f"ap.{self.OWNER_COLUMN} = :token_id",
            f"a.{self.OWNER_COLUMN} = :token_id",
        ]
        params: dict[str, object] = {"token_id": token_id}
        if automation_id is not None:
            where_clauses.append("ap.automation_id = :automation_id")
            params["automation_id"] = automation_id
        if is_active is not None:
            if active_column is None:
                if not is_active:
                    return []
            else:
                where_clauses.append(f"ap.{active_column} = :is_active")
                params["is_active"] = bool(is_active)

        pagination_sql = self._build_pagination_sql(limit=limit, offset=offset, params=params)
        stmt = text(
            f"""
            SELECT
                ap.id,
                ap.automation_id,
                ap.prompt_text,
                {version_expr} AS version,
                {created_expr} AS created_at,
                {active_expr} AS is_active,
                ap.{self.OWNER_COLUMN} AS owner_token_id
            FROM automation_prompts ap
            JOIN automations a ON a.id = ap.automation_id
            WHERE {" AND ".join(where_clauses)}
            ORDER BY {", ".join(order_terms)}
            {pagination_sql}
            """
        )
        rows = self.session.execute(stmt, params).mappings().all()
        items: list[TokenOwnedPromptRecord] = []
        for row in rows:
            item = self._build_prompt_record(row)
            if item is not None:
                items.append(item)
        return items

    def get_prompt_by_id_and_token(
        self,
        *,
        prompt_id: uuid.UUID,
        token_id: uuid.UUID,
    ) -> TokenOwnedPromptRecord | None:
        prompt_columns = self._get_table_columns("automation_prompts")
        automation_columns = self._get_table_columns("automations")
        self._ensure_owner_column(table_name="automation_prompts", columns=prompt_columns)
        self._ensure_owner_column(table_name="automations", columns=automation_columns)
        if "id" not in prompt_columns or "automation_id" not in prompt_columns or "prompt_text" not in prompt_columns:
            return None

        version_expr = "ap.version" if "version" in prompt_columns else "1"
        created_expr = "ap.created_at" if "created_at" in prompt_columns else "now()"
        active_expr, _ = self._build_active_expr(
            table_alias="ap",
            available_columns=prompt_columns,
        )
        stmt = text(
            f"""
            SELECT
                ap.id,
                ap.automation_id,
                ap.prompt_text,
                {version_expr} AS version,
                {created_expr} AS created_at,
                {active_expr} AS is_active,
                ap.{self.OWNER_COLUMN} AS owner_token_id
            FROM automation_prompts ap
            JOIN automations a ON a.id = ap.automation_id
            WHERE ap.id = :prompt_id
              AND ap.{self.OWNER_COLUMN} = :token_id
              AND a.{self.OWNER_COLUMN} = :token_id
            LIMIT 1
            """
        )
        row = self.session.execute(stmt, {"prompt_id": prompt_id, "token_id": token_id}).mappings().first()
        return self._build_prompt_record(row)

    def get_prompt_by_id(self, *, prompt_id: uuid.UUID) -> TokenOwnedPromptRecord | None:
        prompt_columns = self._get_table_columns("automation_prompts")
        if "id" not in prompt_columns or "automation_id" not in prompt_columns or "prompt_text" not in prompt_columns:
            return None

        version_expr = "ap.version" if "version" in prompt_columns else "1"
        created_expr = "ap.created_at" if "created_at" in prompt_columns else "now()"
        owner_expr = f"ap.{self.OWNER_COLUMN}" if self.OWNER_COLUMN in prompt_columns else "NULL::uuid"
        active_expr, _ = self._build_active_expr(
            table_alias="ap",
            available_columns=prompt_columns,
        )
        stmt = text(
            f"""
            SELECT
                ap.id,
                ap.automation_id,
                ap.prompt_text,
                {version_expr} AS version,
                {created_expr} AS created_at,
                {active_expr} AS is_active,
                {owner_expr} AS owner_token_id
            FROM automation_prompts ap
            WHERE ap.id = :prompt_id
            LIMIT 1
            """
        )
        row = self.session.execute(stmt, {"prompt_id": prompt_id}).mappings().first()
        return self._build_prompt_record(row)

    def create_prompt(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
        prompt_text: str,
    ) -> TokenOwnedPromptRecord:
        prompt_metadata = self._get_table_columns_metadata("automation_prompts")
        self._ensure_owner_column(table_name="automation_prompts", columns=set(prompt_metadata.keys()))
        if "id" not in prompt_metadata or "automation_id" not in prompt_metadata or "prompt_text" not in prompt_metadata:
            raise AppException(
                "Shared table 'automation_prompts' is not compatible with external catalog writes.",
                status_code=500,
                code="prompt_schema_incompatible",
            )

        prompt_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        values: dict[str, object] = {
            "id": prompt_id,
            "automation_id": automation_id,
            "prompt_text": str(prompt_text or "").strip(),
            self.OWNER_COLUMN: token_id,
        }
        active_column = self._find_active_column(set(prompt_metadata.keys()))
        if active_column is not None:
            values[active_column] = True
        if "version" in prompt_metadata:
            values["version"] = self._next_prompt_version(
                automation_id=automation_id,
                token_id=token_id,
                prompt_columns=set(prompt_metadata.keys()),
            )
        if "created_at" in prompt_metadata:
            values["created_at"] = now
        if "updated_at" in prompt_metadata:
            values["updated_at"] = now

        required_columns = self._required_columns_without_default(prompt_metadata)
        for column_name in sorted(required_columns):
            if column_name in values:
                continue
            guessed = self._guess_required_prompt_value(
                column_name=column_name,
                prompt_id=prompt_id,
                automation_id=automation_id,
                token_id=token_id,
                now=now,
            )
            if guessed is None:
                raise AppException(
                    "Prompt schema has unsupported required columns for this external operation.",
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

        created = self.get_prompt_by_id_and_token(prompt_id=prompt_id, token_id=token_id)
        if created is None:
            raise AppException(
                "Prompt created but not visible in current token scope.",
                status_code=500,
                code="prompt_create_inconsistent",
                details={"prompt_id": str(prompt_id)},
            )
        return created

    def update_prompt(
        self,
        *,
        token_id: uuid.UUID,
        prompt_id: uuid.UUID,
        prompt_text: str | None = None,
        automation_id: uuid.UUID | None = None,
    ) -> TokenOwnedPromptRecord | None:
        prompt_columns = self._get_table_columns("automation_prompts")
        self._ensure_owner_column(table_name="automation_prompts", columns=prompt_columns)
        if "id" not in prompt_columns:
            return None

        assignments: list[str] = []
        params: dict[str, object] = {
            "prompt_id": prompt_id,
            "token_id": token_id,
        }
        if prompt_text is not None and "prompt_text" in prompt_columns:
            params["prompt_text"] = str(prompt_text).strip()
            assignments.append("prompt_text = :prompt_text")
        if automation_id is not None and "automation_id" in prompt_columns:
            params["automation_id"] = automation_id
            assignments.append("automation_id = :automation_id")
        if self.OWNER_COLUMN in prompt_columns:
            params["owner_token_id"] = token_id
            assignments.append(f"{self.OWNER_COLUMN} = :owner_token_id")
        if "updated_at" in prompt_columns:
            params["updated_at"] = datetime.now(timezone.utc)
            assignments.append("updated_at = :updated_at")
        if not assignments:
            return self.get_prompt_by_id_and_token(prompt_id=prompt_id, token_id=token_id)

        stmt = text(
            f"""
            UPDATE automation_prompts
            SET {", ".join(assignments)}
            WHERE id = :prompt_id
              AND {self.OWNER_COLUMN} = :token_id
            """
        )
        result = self.session.execute(stmt, params)
        if int(result.rowcount or 0) <= 0:
            return None
        return self.get_prompt_by_id_and_token(prompt_id=prompt_id, token_id=token_id)

    def set_prompt_status(
        self,
        *,
        token_id: uuid.UUID,
        prompt_id: uuid.UUID,
        is_active: bool,
    ) -> TokenOwnedPromptRecord | None:
        prompt_columns = self._get_table_columns("automation_prompts")
        self._ensure_owner_column(table_name="automation_prompts", columns=prompt_columns)
        active_column = self._find_active_column(prompt_columns)
        if active_column is None:
            raise AppException(
                "Prompt status field is unavailable in shared schema.",
                status_code=500,
                code="status_field_unavailable",
                details={"table": "automation_prompts"},
            )
        params: dict[str, object] = {
            "prompt_id": prompt_id,
            "token_id": token_id,
            "is_active": bool(is_active),
        }
        assignments = [f"{active_column} = :is_active"]
        if self.OWNER_COLUMN in prompt_columns:
            params["owner_token_id"] = token_id
            assignments.append(f"{self.OWNER_COLUMN} = :owner_token_id")
        if "updated_at" in prompt_columns:
            params["updated_at"] = datetime.now(timezone.utc)
            assignments.append("updated_at = :updated_at")
        stmt = text(
            f"""
            UPDATE automation_prompts
            SET {", ".join(assignments)}
            WHERE id = :prompt_id
              AND {self.OWNER_COLUMN} = :token_id
            """
        )
        result = self.session.execute(stmt, params)
        if int(result.rowcount or 0) <= 0:
            return None
        return self.get_prompt_by_id_and_token(prompt_id=prompt_id, token_id=token_id)

    def delete_prompt_by_id_and_token(
        self,
        *,
        token_id: uuid.UUID,
        prompt_id: uuid.UUID,
    ) -> bool:
        prompt_columns = self._get_table_columns("automation_prompts")
        self._ensure_owner_column(table_name="automation_prompts", columns=prompt_columns)
        stmt = text(
            f"""
            DELETE FROM automation_prompts
            WHERE id = :prompt_id
              AND {self.OWNER_COLUMN} = :token_id
            """
        )
        result = self.session.execute(
            stmt,
            {"prompt_id": prompt_id, "token_id": token_id},
        )
        return int(result.rowcount or 0) > 0

    def _next_prompt_version(
        self,
        *,
        automation_id: uuid.UUID,
        token_id: uuid.UUID,
        prompt_columns: set[str],
    ) -> int:
        if "version" not in prompt_columns:
            return 1
        stmt = text(
            f"""
            SELECT COALESCE(MAX(ap.version), 0)
            FROM automation_prompts ap
            WHERE ap.automation_id = :automation_id
              AND ap.{self.OWNER_COLUMN} = :token_id
            """
        )
        current = self.session.execute(
            stmt,
            {"automation_id": automation_id, "token_id": token_id},
        ).scalar()
        try:
            current_value = int(current or 0)
        except (TypeError, ValueError):
            current_value = 0
        return max(current_value + 1, 1)

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

    def _ensure_owner_column(self, *, table_name: str, columns: set[str]) -> None:
        if self.OWNER_COLUMN in columns:
            return
        raise AppException(
            "Token ownership schema is unavailable. Run latest migrations before using external catalog endpoints.",
            status_code=500,
            code="token_ownership_schema_missing",
            details={"table": table_name, "missing_column": self.OWNER_COLUMN},
        )

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

    def _guess_required_automation_value(
        self,
        *,
        column_name: str,
        column_meta: dict[str, object] | None,
        automation_id: uuid.UUID,
        name: str,
        token_id: uuid.UUID,
        provider_id: uuid.UUID,
        model_id: uuid.UUID,
        credential_id: uuid.UUID | None,
        output_type: str | None,
        result_parser: str | None,
        result_formatter: str | None,
        output_schema: dict[str, object] | None,
        is_active: bool,
        now: datetime,
    ) -> object | None:
        lower_name = str(column_name or "").strip().lower()
        if lower_name == "id":
            return automation_id
        if lower_name == "name" or lower_name.endswith("_name"):
            return name
        if lower_name in self.PROVIDER_CANDIDATES:
            return provider_id
        if lower_name in self.MODEL_CANDIDATES:
            return model_id
        if lower_name in self.CREDENTIAL_CANDIDATES:
            return credential_id
        if lower_name in self.OUTPUT_TYPE_CANDIDATES:
            return str(output_type).strip() if output_type is not None else None
        if lower_name in self.RESULT_PARSER_CANDIDATES:
            return str(result_parser).strip() if result_parser is not None else None
        if lower_name in self.RESULT_FORMATTER_CANDIDATES:
            return str(result_formatter).strip() if result_formatter is not None else None
        if lower_name in self.OUTPUT_SCHEMA_CANDIDATES:
            if output_schema is None:
                return {}
            return self._coerce_output_schema_for_column(
                output_schema=output_schema,
                column_meta=column_meta,
            )
        if lower_name == self.OWNER_COLUMN:
            return token_id
        if lower_name in {"is_active", "active", "enabled"}:
            return bool(is_active)
        if lower_name in {"created_at", "updated_at"}:
            return now
        return None

    def _guess_required_prompt_value(
        self,
        *,
        column_name: str,
        prompt_id: uuid.UUID,
        automation_id: uuid.UUID,
        token_id: uuid.UUID,
        now: datetime,
    ) -> object | None:
        lower_name = str(column_name or "").strip().lower()
        if lower_name == "id":
            return prompt_id
        if lower_name == "automation_id":
            return automation_id
        if lower_name == "prompt_text":
            return ""
        if lower_name == "version":
            return 1
        if lower_name == self.OWNER_COLUMN:
            return token_id
        if lower_name in {"is_active", "active", "enabled"}:
            return True
        if lower_name in {"created_at", "updated_at"}:
            return now
        return None

    @staticmethod
    def _build_automation_record(row: object | None) -> TokenOwnedAutomationRecord | None:
        if row is None:
            return None
        payload = dict(row)
        automation_id = TokenOwnedCatalogRepository._coerce_uuid(payload.get("id"))
        if automation_id is None:
            return None
        return TokenOwnedAutomationRecord(
            id=automation_id,
            name=str(payload.get("name") or "").strip() or str(automation_id),
            provider_id=TokenOwnedCatalogRepository._coerce_uuid(payload.get("provider_id")),
            model_id=TokenOwnedCatalogRepository._coerce_uuid(payload.get("model_id")),
            credential_id=TokenOwnedCatalogRepository._coerce_uuid(payload.get("credential_id")),
            output_type=TokenOwnedCatalogRepository._coerce_optional_str(payload.get("output_type")),
            result_parser=TokenOwnedCatalogRepository._coerce_optional_str(payload.get("result_parser")),
            result_formatter=TokenOwnedCatalogRepository._coerce_optional_str(payload.get("result_formatter")),
            output_schema=TokenOwnedCatalogRepository._coerce_schema_dict(payload.get("output_schema")),
            is_active=TokenOwnedCatalogRepository._coerce_bool(payload.get("is_active"), default=True),
            owner_token_id=TokenOwnedCatalogRepository._coerce_uuid(payload.get("owner_token_id")),
        )

    @staticmethod
    def _build_prompt_record(row: object | None) -> TokenOwnedPromptRecord | None:
        if row is None:
            return None
        payload = dict(row)
        prompt_id = TokenOwnedCatalogRepository._coerce_uuid(payload.get("id"))
        automation_id = TokenOwnedCatalogRepository._coerce_uuid(payload.get("automation_id"))
        if prompt_id is None or automation_id is None:
            return None
        raw_created_at = payload.get("created_at")
        if isinstance(raw_created_at, datetime):
            created_at = raw_created_at
        else:
            created_at = datetime.now(timezone.utc)
        try:
            version = int(payload.get("version") or 1)
        except (TypeError, ValueError):
            version = 1
        return TokenOwnedPromptRecord(
            id=prompt_id,
            automation_id=automation_id,
            prompt_text=str(payload.get("prompt_text") or ""),
            version=max(version, 1),
            created_at=created_at,
            is_active=TokenOwnedCatalogRepository._coerce_bool(payload.get("is_active"), default=True),
            owner_token_id=TokenOwnedCatalogRepository._coerce_uuid(payload.get("owner_token_id")),
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
    def _coerce_optional_str(value: object | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _coerce_schema_dict(value: object | None) -> dict[str, object] | None:
        if value is None:
            return None
        if isinstance(value, dict):
            return {str(key): value[key] for key in value}
        raw = str(value).strip()
        if not raw:
            return None
        try:
            loaded = json.loads(raw)
        except Exception:
            return None
        if isinstance(loaded, dict):
            return {str(key): loaded[key] for key in loaded}
        return None

    @staticmethod
    def _find_active_column(available_columns: set[str]) -> str | None:
        for candidate in TokenOwnedCatalogRepository.ACTIVE_CANDIDATES:
            if candidate in available_columns:
                return candidate
        return None

    @staticmethod
    def _build_active_expr(*, table_alias: str, available_columns: set[str]) -> tuple[str, str | None]:
        active_column = TokenOwnedCatalogRepository._find_active_column(available_columns)
        if active_column is None:
            return "TRUE", None
        return f"{table_alias}.{active_column}", active_column

    def _build_automation_select_sql(self, *, table_alias: str, available_columns: set[str]) -> str:
        active_expr, _ = self._build_active_expr(table_alias=table_alias, available_columns=available_columns)
        owner_expr = f"{table_alias}.{self.OWNER_COLUMN}" if self.OWNER_COLUMN in available_columns else "NULL::uuid"
        provider_expr = self._build_candidate_expr(
            table_alias=table_alias,
            available_columns=available_columns,
            candidates=self.PROVIDER_CANDIDATES,
            default_sql="NULL::text",
            cast_text=True,
        )
        model_expr = self._build_candidate_expr(
            table_alias=table_alias,
            available_columns=available_columns,
            candidates=self.MODEL_CANDIDATES,
            default_sql="NULL::text",
            cast_text=True,
        )
        credential_expr = self._build_candidate_expr(
            table_alias=table_alias,
            available_columns=available_columns,
            candidates=self.CREDENTIAL_CANDIDATES,
            default_sql="NULL::text",
            cast_text=True,
        )
        output_type_expr = self._build_candidate_expr(
            table_alias=table_alias,
            available_columns=available_columns,
            candidates=self.OUTPUT_TYPE_CANDIDATES,
            default_sql="NULL::text",
            cast_text=False,
        )
        result_parser_expr = self._build_candidate_expr(
            table_alias=table_alias,
            available_columns=available_columns,
            candidates=self.RESULT_PARSER_CANDIDATES,
            default_sql="NULL::text",
            cast_text=False,
        )
        result_formatter_expr = self._build_candidate_expr(
            table_alias=table_alias,
            available_columns=available_columns,
            candidates=self.RESULT_FORMATTER_CANDIDATES,
            default_sql="NULL::text",
            cast_text=False,
        )
        output_schema_expr = self._build_candidate_expr(
            table_alias=table_alias,
            available_columns=available_columns,
            candidates=self.OUTPUT_SCHEMA_CANDIDATES,
            default_sql="NULL::text",
            cast_text=True,
        )
        return (
            f"{table_alias}.id AS id, "
            f"{table_alias}.name AS name, "
            f"{provider_expr} AS provider_id, "
            f"{model_expr} AS model_id, "
            f"{credential_expr} AS credential_id, "
            f"{output_type_expr} AS output_type, "
            f"{result_parser_expr} AS result_parser, "
            f"{result_formatter_expr} AS result_formatter, "
            f"{output_schema_expr} AS output_schema, "
            f"{active_expr} AS is_active, "
            f"{owner_expr} AS owner_token_id"
        )

    @staticmethod
    def _find_first_available_column(available_columns: set[str], candidates: tuple[str, ...]) -> str | None:
        for candidate in candidates:
            if candidate in available_columns:
                return candidate
        return None

    @staticmethod
    def _build_candidate_expr(
        *,
        table_alias: str,
        available_columns: set[str],
        candidates: tuple[str, ...],
        default_sql: str,
        cast_text: bool,
    ) -> str:
        for candidate in candidates:
            if candidate in available_columns:
                if cast_text:
                    return f"({table_alias}.{candidate})::text"
                return f"{table_alias}.{candidate}"
        return default_sql

    @staticmethod
    def _coerce_output_schema_for_column(
        *,
        output_schema: object,
        column_meta: dict[str, object] | None,
    ) -> object:
        if not isinstance(output_schema, dict):
            if output_schema is None:
                return None
            return str(output_schema)
        data_type = str((column_meta or {}).get("data_type") or "").strip().lower()
        udt_name = str((column_meta or {}).get("udt_name") or "").strip().lower()
        merged_type = f"{data_type} {udt_name}".strip()
        if "json" in merged_type:
            return output_schema
        return json.dumps(output_schema, ensure_ascii=False)

    @staticmethod
    def _resolve_json_bind_type(column_meta: dict[str, object] | None) -> object | None:
        data_type = str((column_meta or {}).get("data_type") or "").strip().lower()
        udt_name = str((column_meta or {}).get("udt_name") or "").strip().lower()
        merged_type = f"{data_type} {udt_name}".strip()
        if "jsonb" in merged_type:
            return JSONB()
        if "json" in merged_type:
            return JSON()
        return None

    def _apply_json_typed_bindparams(
        self,
        *,
        stmt,
        params: dict[str, object],
        param_to_column: dict[str, str],
        metadata: dict[str, dict[str, object]],
    ):
        bind_params: list[object] = []
        for param_name, column_name in param_to_column.items():
            if param_name not in params:
                continue
            bind_type = self._resolve_json_bind_type(metadata.get(column_name))
            if bind_type is None:
                continue
            value = params.get(param_name)
            if isinstance(value, (dict, list)) or value is None:
                bind_params.append(bindparam(param_name, type_=bind_type))
        if not bind_params:
            return stmt
        return stmt.bindparams(*bind_params)

    @staticmethod
    def _build_pagination_sql(*, limit: int | None, offset: int | None, params: dict[str, object]) -> str:
        clauses: list[str] = []
        if limit is not None:
            params["limit"] = max(int(limit), 0)
            clauses.append("LIMIT :limit")
        if offset is not None:
            params["offset"] = max(int(offset), 0)
            clauses.append("OFFSET :offset")
        return " ".join(clauses)

    @staticmethod
    def _coerce_bool(value: object | None, *, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "t", "yes", "y"}:
            return True
        if normalized in {"0", "false", "f", "no", "n"}:
            return False
        return default
