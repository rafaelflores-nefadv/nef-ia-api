from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.exceptions import AppException


@dataclass(slots=True, frozen=True)
class PromptTestAutomationRecord:
    id: uuid.UUID
    name: str
    slug: str | None
    provider_slug: str | None
    model_slug: str | None
    provider_id: uuid.UUID | None
    model_id: uuid.UUID | None
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None


class PromptTestAutomationRepository:
    """
    Isolated persistence for prompt-test runtime automations.

    This table is intentionally independent from official `automations`.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def ensure_schema(self) -> None:
        create_stmt = text(
            """
            CREATE TABLE IF NOT EXISTS test_automations (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(180) NOT NULL,
                slug VARCHAR(180) NOT NULL UNIQUE,
                provider_slug VARCHAR(120) NULL,
                model_slug VARCHAR(160) NULL,
                provider_id VARCHAR(36) NULL,
                model_id VARCHAR(36) NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
            """
        )
        index_slug_stmt = text(
            """
            CREATE INDEX IF NOT EXISTS ix_test_automations_slug
            ON test_automations (slug)
            """
        )
        index_updated_stmt = text(
            """
            CREATE INDEX IF NOT EXISTS ix_test_automations_updated_at
            ON test_automations (updated_at)
            """
        )
        try:
            self.session.execute(create_stmt)
            self.session.execute(index_slug_stmt)
            self.session.execute(index_updated_stmt)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            raise AppException(
                "Failed to initialize prompt-test automation schema.",
                status_code=500,
                code="test_prompt_runtime_schema_init_failed",
                details={"table": "test_automations", "error": str(exc)},
            ) from exc

    def get_by_id(self, automation_id: uuid.UUID) -> PromptTestAutomationRecord | None:
        stmt = text(
            """
            SELECT
                id,
                name,
                slug,
                provider_slug,
                model_slug,
                provider_id,
                model_id,
                is_active,
                created_at,
                updated_at
            FROM test_automations
            WHERE id = :automation_id
            LIMIT 1
            """
        )
        row = self.session.execute(stmt, {"automation_id": str(automation_id)}).mappings().first()
        if row is None:
            return None
        return self._map_row(row)

    def find_runtime(
        self,
        *,
        preferred_id: uuid.UUID | None,
        slug: str,
        name: str,
    ) -> PromptTestAutomationRecord | None:
        if preferred_id is not None:
            record = self.get_by_id(preferred_id)
            if record is not None:
                return record

        normalized_slug = str(slug or "").strip().lower()
        if normalized_slug:
            slug_stmt = text(
                """
                SELECT
                    id,
                    name,
                    slug,
                    provider_slug,
                    model_slug,
                    provider_id,
                    model_id,
                    is_active,
                    created_at,
                    updated_at
                FROM test_automations
                WHERE lower(slug) = :slug
                LIMIT 1
                """
            )
            row = self.session.execute(slug_stmt, {"slug": normalized_slug}).mappings().first()
            if row is not None:
                return self._map_row(row)

        normalized_name = str(name or "").strip().lower()
        if normalized_name:
            name_stmt = text(
                """
                SELECT
                    id,
                    name,
                    slug,
                    provider_slug,
                    model_slug,
                    provider_id,
                    model_id,
                    is_active,
                    created_at,
                    updated_at
                FROM test_automations
                WHERE lower(name) = :name
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """
            )
            row = self.session.execute(name_stmt, {"name": normalized_name}).mappings().first()
            if row is not None:
                return self._map_row(row)
        return None

    def create(
        self,
        *,
        automation_id: uuid.UUID,
        name: str,
        slug: str,
        provider_slug: str | None,
        model_slug: str | None,
        provider_id: uuid.UUID | None,
        model_id: uuid.UUID | None,
        is_active: bool = True,
    ) -> PromptTestAutomationRecord:
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "id": str(automation_id),
            "name": str(name or "").strip(),
            "slug": str(slug or "").strip().lower(),
            "provider_slug": self._normalize_slug(provider_slug),
            "model_slug": self._normalize_slug(model_slug),
            "provider_id": str(provider_id) if provider_id is not None else None,
            "model_id": str(model_id) if model_id is not None else None,
            "is_active": bool(is_active),
            "created_at": now,
            "updated_at": now,
        }
        insert_stmt = text(
            """
            INSERT INTO test_automations (
                id,
                name,
                slug,
                provider_slug,
                model_slug,
                provider_id,
                model_id,
                is_active,
                created_at,
                updated_at
            ) VALUES (
                :id,
                :name,
                :slug,
                :provider_slug,
                :model_slug,
                :provider_id,
                :model_id,
                :is_active,
                :created_at,
                :updated_at
            )
            """
        )
        try:
            self.session.execute(insert_stmt, values)
            self.session.commit()
        except Exception:
            # Race-safe fallback in case another request creates the same runtime row.
            self.session.rollback()
            existing = self.find_runtime(preferred_id=automation_id, slug=values["slug"], name=values["name"])
            if existing is not None:
                return existing
            raise
        created = self.get_by_id(automation_id)
        if created is None:
            raise AppException(
                "Prompt-test automation was created but could not be read back.",
                status_code=500,
                code="test_prompt_runtime_invalid",
                details={"automation_id": str(automation_id)},
            )
        return created

    def update(
        self,
        *,
        automation_id: uuid.UUID,
        name: str,
        slug: str,
        provider_slug: str | None,
        model_slug: str | None,
        provider_id: uuid.UUID | None,
        model_id: uuid.UUID | None,
        is_active: bool,
    ) -> PromptTestAutomationRecord:
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "automation_id": str(automation_id),
            "name": str(name or "").strip(),
            "slug": str(slug or "").strip().lower(),
            "provider_slug": self._normalize_slug(provider_slug),
            "model_slug": self._normalize_slug(model_slug),
            "provider_id": str(provider_id) if provider_id is not None else None,
            "model_id": str(model_id) if model_id is not None else None,
            "is_active": bool(is_active),
            "updated_at": now,
        }
        stmt = text(
            """
            UPDATE test_automations
            SET
                name = :name,
                slug = :slug,
                provider_slug = :provider_slug,
                model_slug = :model_slug,
                provider_id = :provider_id,
                model_id = :model_id,
                is_active = :is_active,
                updated_at = :updated_at
            WHERE id = :automation_id
            """
        )
        self.session.execute(stmt, values)
        self.session.commit()
        updated = self.get_by_id(automation_id)
        if updated is None:
            raise AppException(
                "Prompt-test automation update could not be confirmed.",
                status_code=500,
                code="test_prompt_runtime_invalid",
                details={"automation_id": str(automation_id)},
            )
        return updated

    @staticmethod
    def _normalize_slug(value: str | None) -> str | None:
        normalized = str(value or "").strip().lower()
        return normalized or None

    @staticmethod
    def _coerce_uuid(value: object | None) -> uuid.UUID | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except ValueError:
            return None

    @classmethod
    def _map_row(cls, row: Any) -> PromptTestAutomationRecord:
        raw_id = cls._coerce_uuid(row.get("id"))
        if raw_id is None:
            raise AppException(
                "Prompt-test automation row has invalid identifier.",
                status_code=500,
                code="test_prompt_runtime_invalid",
                details={"id": str(row.get("id") or "")},
            )
        normalized_name = str(row.get("name") or "").strip() or str(raw_id)
        slug = str(row.get("slug") or "").strip().lower() or None
        provider_slug = cls._normalize_slug(row.get("provider_slug"))
        model_slug = cls._normalize_slug(row.get("model_slug"))
        return PromptTestAutomationRecord(
            id=raw_id,
            name=normalized_name,
            slug=slug,
            provider_slug=provider_slug,
            model_slug=model_slug,
            provider_id=cls._coerce_uuid(row.get("provider_id")),
            model_id=cls._coerce_uuid(row.get("model_id")),
            is_active=bool(row.get("is_active", True)),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
