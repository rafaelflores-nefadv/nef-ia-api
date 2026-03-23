"""enforce prompt owner scope consistency with parent automation

Revision ID: 20260322_0009
Revises: 20260322_0008
Create Date: 2026-03-22 14:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url

from app.core.config import get_settings


# revision identifiers, used by Alembic.
revision: str = "20260322_0009"
down_revision: Union[str, Sequence[str], None] = "20260322_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _apply_upgrade_ddl(connection: Connection) -> None:
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
                    CREATE INDEX IF NOT EXISTS ix_automations_owner_token_id_id
                    ON automations (owner_token_id, id);
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
                      AND table_name = 'automations'
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE constraint_schema = current_schema()
                      AND table_name = 'automations'
                      AND constraint_name = 'uq_automations_id_owner_token_id'
                )
                THEN
                    ALTER TABLE automations
                    ADD CONSTRAINT uq_automations_id_owner_token_id
                    UNIQUE (id, owner_token_id);
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
                AND EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = 'automations'
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE constraint_schema = current_schema()
                      AND table_name = 'automation_prompts'
                      AND constraint_name = 'fk_automation_prompts_automation_id_owner_token_id_automations'
                )
                THEN
                    ALTER TABLE automation_prompts
                    ADD CONSTRAINT fk_automation_prompts_automation_id_owner_token_id_automations
                    FOREIGN KEY (automation_id, owner_token_id)
                    REFERENCES automations (id, owner_token_id)
                    ON DELETE RESTRICT
                    NOT VALID;
                END IF;
            END
            $$;
            """
        )
    )


def _apply_downgrade_ddl(connection: Connection) -> None:
    connection.execute(
        text(
            "ALTER TABLE IF EXISTS automation_prompts "
            "DROP CONSTRAINT IF EXISTS fk_automation_prompts_automation_id_owner_token_id_automations"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE IF EXISTS automations "
            "DROP CONSTRAINT IF EXISTS uq_automations_id_owner_token_id"
        )
    )
    connection.execute(text("DROP INDEX IF EXISTS ix_automations_owner_token_id_id"))


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
