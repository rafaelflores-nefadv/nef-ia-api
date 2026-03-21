from dataclasses import dataclass
from datetime import datetime, timezone
import logging
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
