"""ensure shared automation_prompts table exists for external catalog flows

Revision ID: 20260323_0013
Revises: 20260322_0012
Create Date: 2026-03-23 09:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url

from app.core.config import get_settings


# revision identifiers, used by Alembic.
revision: str = "20260323_0013"
down_revision: Union[str, Sequence[str], None] = "20260322_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def _constraint_exists(connection: Connection, *, table_name: str, constraint_name: str) -> bool:
    exists = connection.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.table_constraints
                WHERE constraint_schema = current_schema()
                  AND table_name = :table_name
                  AND constraint_name = :constraint_name
            )
            """
        ),
        {"table_name": table_name, "constraint_name": constraint_name},
    ).scalar()
    return bool(exists)


def _apply_upgrade_ddl(connection: Connection) -> None:
    if not _table_exists(connection, "automations"):
        return

    if not _table_exists(connection, "automation_prompts"):
        connection.execute(
            text(
                """
                CREATE TABLE automation_prompts (
                    id UUID PRIMARY KEY,
                    automation_id UUID NOT NULL,
                    prompt_text TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    owner_token_id UUID NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE
                )
                """
            )
        )
    else:
        connection.execute(text("ALTER TABLE automation_prompts ADD COLUMN IF NOT EXISTS owner_token_id UUID"))
        connection.execute(text("ALTER TABLE automation_prompts ADD COLUMN IF NOT EXISTS is_active BOOLEAN"))
        connection.execute(text("ALTER TABLE automation_prompts ADD COLUMN IF NOT EXISTS version INTEGER"))
        connection.execute(text("ALTER TABLE automation_prompts ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ"))
        connection.execute(text("ALTER TABLE automation_prompts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ"))

        connection.execute(text("UPDATE automation_prompts SET is_active = TRUE WHERE is_active IS NULL"))
        connection.execute(text("ALTER TABLE automation_prompts ALTER COLUMN is_active SET DEFAULT TRUE"))
        connection.execute(text("ALTER TABLE automation_prompts ALTER COLUMN is_active SET NOT NULL"))

        connection.execute(text("UPDATE automation_prompts SET version = 1 WHERE version IS NULL"))
        connection.execute(text("ALTER TABLE automation_prompts ALTER COLUMN version SET DEFAULT 1"))
        connection.execute(text("ALTER TABLE automation_prompts ALTER COLUMN version SET NOT NULL"))

        connection.execute(text("UPDATE automation_prompts SET created_at = now() WHERE created_at IS NULL"))
        connection.execute(text("ALTER TABLE automation_prompts ALTER COLUMN created_at SET DEFAULT now()"))
        connection.execute(text("ALTER TABLE automation_prompts ALTER COLUMN created_at SET NOT NULL"))

        connection.execute(text("UPDATE automation_prompts SET updated_at = now() WHERE updated_at IS NULL"))
        connection.execute(text("ALTER TABLE automation_prompts ALTER COLUMN updated_at SET DEFAULT now()"))
        connection.execute(text("ALTER TABLE automation_prompts ALTER COLUMN updated_at SET NOT NULL"))

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_automation_prompts_automation_id ON automation_prompts (automation_id)"))
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_automation_prompts_owner_token_id ON automation_prompts (owner_token_id)")
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_automation_prompts_owner_token_id_automation_id "
            "ON automation_prompts (owner_token_id, automation_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_automation_prompts_owner_token_id_is_active "
            "ON automation_prompts (owner_token_id, is_active)"
        )
    )
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_automation_prompts_is_active ON automation_prompts (is_active)"))

    # Backfill owner scope when parent automation already has owner_token_id.
    connection.execute(
        text(
            """
            UPDATE automation_prompts ap
            SET owner_token_id = a.owner_token_id
            FROM automations a
            WHERE ap.automation_id = a.id
              AND ap.owner_token_id IS NULL
            """
        )
    )

    if _table_exists(connection, "django_ai_api_tokens") and not _constraint_exists(
        connection,
        table_name="automation_prompts",
        constraint_name="fk_automation_prompts_owner_token_id_django_ai_api_tokens",
    ):
        connection.execute(
            text(
                """
                ALTER TABLE automation_prompts
                ADD CONSTRAINT fk_automation_prompts_owner_token_id_django_ai_api_tokens
                FOREIGN KEY (owner_token_id)
                REFERENCES django_ai_api_tokens (id)
                ON DELETE RESTRICT
                """
            )
        )

    if not _constraint_exists(
        connection,
        table_name="automations",
        constraint_name="uq_automations_id_owner_token_id",
    ):
        connection.execute(
            text(
                """
                ALTER TABLE automations
                ADD CONSTRAINT uq_automations_id_owner_token_id
                UNIQUE (id, owner_token_id)
                """
            )
        )

    if not _constraint_exists(
        connection,
        table_name="automation_prompts",
        constraint_name="fk_automation_prompts_automation_id_owner_token_id_automations",
    ):
        connection.execute(
            text(
                """
                ALTER TABLE automation_prompts
                ADD CONSTRAINT fk_automation_prompts_automation_id_owner_token_id_automations
                FOREIGN KEY (automation_id, owner_token_id)
                REFERENCES automations (id, owner_token_id)
                ON DELETE RESTRICT
                NOT VALID
                """
            )
        )


def _apply_downgrade_ddl(connection: Connection) -> None:
    # Intentionally conservative to avoid dropping production data.
    connection.execute(
        text(
            "ALTER TABLE IF EXISTS automation_prompts "
            "DROP CONSTRAINT IF EXISTS fk_automation_prompts_automation_id_owner_token_id_automations"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE IF EXISTS automation_prompts "
            "DROP CONSTRAINT IF EXISTS fk_automation_prompts_owner_token_id_django_ai_api_tokens"
        )
    )
    connection.execute(text("DROP INDEX IF EXISTS ix_automation_prompts_is_active"))
    connection.execute(text("DROP INDEX IF EXISTS ix_automation_prompts_owner_token_id_is_active"))
    connection.execute(text("DROP INDEX IF EXISTS ix_automation_prompts_owner_token_id_automation_id"))
    connection.execute(text("DROP INDEX IF EXISTS ix_automation_prompts_owner_token_id"))
    connection.execute(text("DROP INDEX IF EXISTS ix_automation_prompts_automation_id"))


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

