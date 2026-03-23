"""add runtime catalog fields to shared automations table

Revision ID: 20260322_0012
Revises: 20260322_0011
Create Date: 2026-03-22 21:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url

from app.core.config import get_settings


# revision identifiers, used by Alembic.
revision: str = "20260322_0012"
down_revision: Union[str, Sequence[str], None] = "20260322_0011"
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


def _apply_upgrade_ddl(connection: Connection) -> None:
    if not _table_exists(connection, "automations"):
        return

    connection.execute(text("ALTER TABLE automations ADD COLUMN IF NOT EXISTS provider_id UUID"))
    connection.execute(text("ALTER TABLE automations ADD COLUMN IF NOT EXISTS model_id UUID"))
    connection.execute(text("ALTER TABLE automations ADD COLUMN IF NOT EXISTS credential_id UUID"))
    connection.execute(text("ALTER TABLE automations ADD COLUMN IF NOT EXISTS output_type VARCHAR(64)"))
    connection.execute(text("ALTER TABLE automations ADD COLUMN IF NOT EXISTS result_parser VARCHAR(64)"))
    connection.execute(text("ALTER TABLE automations ADD COLUMN IF NOT EXISTS result_formatter VARCHAR(64)"))
    connection.execute(text("ALTER TABLE automations ADD COLUMN IF NOT EXISTS output_schema JSONB"))

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_automations_provider_id ON automations (provider_id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_automations_model_id ON automations (model_id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_automations_credential_id ON automations (credential_id)"))
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_automations_owner_token_id_provider_id_model_id "
            "ON automations (owner_token_id, provider_id, model_id)"
        )
    )


def _apply_downgrade_ddl(connection: Connection) -> None:
    connection.execute(text("DROP INDEX IF EXISTS ix_automations_owner_token_id_provider_id_model_id"))
    connection.execute(text("DROP INDEX IF EXISTS ix_automations_credential_id"))
    connection.execute(text("DROP INDEX IF EXISTS ix_automations_model_id"))
    connection.execute(text("DROP INDEX IF EXISTS ix_automations_provider_id"))

    connection.execute(text("ALTER TABLE IF EXISTS automations DROP COLUMN IF EXISTS output_schema"))
    connection.execute(text("ALTER TABLE IF EXISTS automations DROP COLUMN IF EXISTS result_formatter"))
    connection.execute(text("ALTER TABLE IF EXISTS automations DROP COLUMN IF EXISTS result_parser"))
    connection.execute(text("ALTER TABLE IF EXISTS automations DROP COLUMN IF EXISTS output_type"))
    connection.execute(text("ALTER TABLE IF EXISTS automations DROP COLUMN IF EXISTS credential_id"))
    connection.execute(text("ALTER TABLE IF EXISTS automations DROP COLUMN IF EXISTS model_id"))
    connection.execute(text("ALTER TABLE IF EXISTS automations DROP COLUMN IF EXISTS provider_id"))


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
