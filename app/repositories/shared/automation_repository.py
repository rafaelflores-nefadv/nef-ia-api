from dataclasses import dataclass
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.shared import Automation, AutomationPrompt


@dataclass(slots=True)
class SharedAutomationRuntimeRecord:
    automation_id: uuid.UUID
    prompt_text: str
    prompt_version: int
    provider_slug: str | None
    model_slug: str | None


class SharedAutomationRepository:
    """Repository for general-system automation data (source of truth)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_automation_by_id(self, automation_id: uuid.UUID) -> Automation | None:
        stmt = select(Automation).where(Automation.id == automation_id)
        return self.session.execute(stmt).scalar_one_or_none()

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
            candidates=["provider_slug", "provider", "ai_provider_slug", "ai_provider", "llm_provider"],
        )
        prompt_model_expr, _ = self._build_runtime_expr(
            table_alias="ap",
            available_columns=prompt_columns,
            candidates=["model_slug", "model", "ai_model_slug", "ai_model", "llm_model"],
        )
        automation_provider_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["provider_slug", "provider", "ai_provider_slug", "ai_provider", "llm_provider"],
        )
        automation_model_expr, _ = self._build_runtime_expr(
            table_alias="a",
            available_columns=automation_columns,
            candidates=["model_slug", "model", "ai_model_slug", "ai_model", "llm_model"],
        )

        runtime_stmt = text(
            f"""
            SELECT
                ap.automation_id,
                ap.prompt_text,
                ap.version AS prompt_version,
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
    def _build_runtime_expr(*, table_alias: str, available_columns: set[str], candidates: list[str]) -> tuple[str, str | None]:
        for candidate in candidates:
            if candidate in available_columns:
                return f"{table_alias}.{candidate}", candidate
        return "NULL::text", None

    @staticmethod
    def _clean_runtime_value(value: object | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None
