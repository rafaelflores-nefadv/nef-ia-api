"""add is_active to external catalog tables for full CRUD status operations

Revision ID: 20260322_0010
Revises: 20260322_0009
Create Date: 2026-03-22 15:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url

from app.core.config import get_settings


# revision identifiers, used by Alembic.
revision: str = "20260322_0010"
down_revision: Union[str, Sequence[str], None] = "20260322_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_is_active_column(connection: Connection, table_name: str) -> None:
    connection.execute(text(f"ALTER TABLE IF EXISTS {table_name} ADD COLUMN IF NOT EXISTS is_active BOOLEAN"))
    connection.execute(text(f"UPDATE {table_name} SET is_active = TRUE WHERE is_active IS NULL"))
    connection.execute(text(f"ALTER TABLE {table_name} ALTER COLUMN is_active SET DEFAULT TRUE"))
    connection.execute(text(f"ALTER TABLE {table_name} ALTER COLUMN is_active SET NOT NULL"))


def _table_exists(connection: Connection, table_name: str) -> bool:
    exists = connection.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
            )
            """
        ),
        {"table_name": table_name},
    ).scalar()
    return bool(exists)


def _apply_upgrade_ddl(connection: Connection) -> None:
    if _table_exists(connection, "automations"):
        _add_is_active_column(connection, "automations")

    if _table_exists(connection, "automation_prompts"):
        _add_is_active_column(connection, "automation_prompts")

    connection.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = 'automations'
                )
                THEN
                    CREATE INDEX IF NOT EXISTS ix_automations_owner_token_id_is_active
                    ON automations (owner_token_id, is_active);
                    CREATE INDEX IF NOT EXISTS ix_automations_is_active
                    ON automations (is_active);
                END IF;
            END
            $$;
            """
        )
    )

    connection.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = 'automation_prompts'
                )
                THEN
                    CREATE INDEX IF NOT EXISTS ix_automation_prompts_owner_token_id_is_active
                    ON automation_prompts (owner_token_id, is_active);
                    CREATE INDEX IF NOT EXISTS ix_automation_prompts_is_active
                    ON automation_prompts (is_active);
                END IF;
            END
            $$;
            """
        )
    )


def _apply_downgrade_ddl(connection: Connection) -> None:
    connection.execute(text("DROP INDEX IF EXISTS ix_automation_prompts_is_active"))
    connection.execute(text("DROP INDEX IF EXISTS ix_automation_prompts_owner_token_id_is_active"))
    connection.execute(text("DROP INDEX IF EXISTS ix_automations_is_active"))
    connection.execute(text("DROP INDEX IF EXISTS ix_automations_owner_token_id_is_active"))

    connection.execute(text("ALTER TABLE IF EXISTS automation_prompts DROP COLUMN IF EXISTS is_active"))
    connection.execute(text("ALTER TABLE IF EXISTS automations DROP COLUMN IF EXISTS is_active"))


def _run_in_shared_database(*, upgrade_mode: bool) -> None:
    settings = get_settings()
    operational_url = str(settings.resolved_database_url or "").strip()
    shared_url = str(settings.resolved_shared_database_url or "").strip()
    if not shared_url:
        return

    try:
        same_database = bool(operational_url) and make_url(shared_url) == make_url(operational_url)
    except Exception:
        same_database = operational_url == shared_url
    if same_database:
        return

    engine = create_engine(shared_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            if upgrade_mode:
                _apply_upgrade_ddl(connection)
            else:
                _apply_downgrade_ddl(connection)
    finally:
        engine.dispose()


def upgrade() -> None:
    connection = op.get_bind()
    _apply_upgrade_ddl(connection)
    _run_in_shared_database(upgrade_mode=True)


def downgrade() -> None:
    connection = op.get_bind()
    _apply_downgrade_ddl(connection)
    _run_in_shared_database(upgrade_mode=False)
