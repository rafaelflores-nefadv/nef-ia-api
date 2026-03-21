from dataclasses import dataclass
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.shared import AutomationPrompt


@dataclass(slots=True)
class SharedAutomationRecord:
    id: uuid.UUID
    name: str
    is_active: bool


@dataclass(slots=True)
class SharedAutomationRuntimeRecord:
    automation_id: uuid.UUID
    prompt_text: str
    prompt_version: int
    automation_slug: str | None
    is_test_automation: bool | None
    provider_slug: str | None
    model_slug: str | None


@dataclass(slots=True)
class SharedAutomationTargetRecord:
    automation_id: uuid.UUID
    automation_slug: str | None
    is_test_automation: bool | None
    provider_slug: str | None
    model_slug: str | None


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

        prompt_provider_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=[
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
        prompt_model_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=[
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
        automation_provider_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=[
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
        automation_model_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=[
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
                ap.prompt_text,
                ap.version AS prompt_version,
                {automation_slug_expr} AS automation_slug,
                {is_test_expr} AS is_test_automation,
                COALESCE({prompt_provider_expr}, {automation_provider_expr}) AS provider_slug,
                COALESCE({prompt_model_expr}, {automation_model_expr}) AS model_slug
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
            prompt_text=str(row["prompt_text"]),
            prompt_version=int(row["prompt_version"]),
            automation_slug=self._clean_runtime_value(row.get("automation_slug")),
            is_test_automation=self._coerce_runtime_bool(row.get("is_test_automation")),
            provider_slug=self._clean_runtime_value(row.get("provider_slug")),
            model_slug=self._clean_runtime_value(row.get("model_slug")),
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
        provider_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=[
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
        model_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=[
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
        stmt = text(
            f"""
            SELECT
                a.id AS automation_id,
                {slug_expr} AS automation_slug,
                {is_test_expr} AS is_test_automation,
                {provider_expr} AS provider_slug,
                {model_expr} AS model_slug
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
            provider_slug=self._clean_runtime_value(row.get("provider_slug")),
            model_slug=self._clean_runtime_value(row.get("model_slug")),
        )

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

    @staticmethod
    def _build_automation_select_sql(*, table_alias: str, available_columns: set[str]) -> str:
        name_expr = f"{table_alias}.name" if "name" in available_columns else f"{table_alias}.id::text"
        active_expr = (
            f"{table_alias}.is_active"
            if "is_active" in available_columns
            else "TRUE"
        )
        return (
            f"{table_alias}.id AS id, "
            f"{name_expr} AS name, "
            f"{active_expr} AS is_active"
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
