"""remove legacy prompt-test runtime structures

Revision ID: 20260321_0007
Revises: 20260321_0006
Create Date: 2026-03-21 18:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings


# revision identifiers, used by Alembic.
revision: str = "20260321_0007"
down_revision: Union[str, Sequence[str], None] = "20260321_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cleanup_shared_test_automation_table() -> None:
    settings = get_settings()
    shared_url = str(settings.resolved_shared_database_url or "").strip()
    if not shared_url:
        return

    engine = create_engine(shared_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS test_automations"))
    finally:
        engine.dispose()


def _recreate_shared_test_automation_table() -> None:
    settings = get_settings()
    shared_url = str(settings.resolved_shared_database_url or "").strip()
    if not shared_url:
        return

    engine = create_engine(shared_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS test_automations (
                        id UUID PRIMARY KEY,
                        preferred_id UUID NULL,
                        slug VARCHAR(220) NOT NULL UNIQUE,
                        name VARCHAR(180) NOT NULL,
                        provider_slug VARCHAR(120) NOT NULL,
                        model_slug VARCHAR(160) NOT NULL,
                        provider_id UUID NULL,
                        model_id UUID NULL,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        is_technical_runtime BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_test_automations_slug ON test_automations (slug)"))
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_test_automations_is_technical_runtime "
                    "ON test_automations (is_technical_runtime)"
                )
            )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_test_automations_updated_at ON test_automations (updated_at)")
            )
    finally:
        engine.dispose()


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_django_ai_prompt_test_execution_contexts_test_automation_id")
    op.execute("DROP INDEX IF EXISTS ix_django_ai_prompt_test_execution_contexts_execution_id")
    op.execute("DROP TABLE IF EXISTS django_ai_prompt_test_execution_contexts")
    _cleanup_shared_test_automation_table()


def downgrade() -> None:
    op.create_table(
        "django_ai_prompt_test_execution_contexts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("test_automation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("test_automation_name", sa.String(length=180), nullable=False),
        sa.Column("provider_slug", sa.String(length=120), nullable=False),
        sa.Column("model_slug", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["analysis_executions.id"],
            name=op.f("fk_django_ai_prompt_test_execution_contexts_execution_id_analysis_executions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_prompt_test_execution_contexts")),
        sa.UniqueConstraint(
            "execution_id",
            name=op.f("uq_django_ai_prompt_test_execution_contexts_execution_id"),
        ),
    )
    op.create_index(
        op.f("ix_django_ai_prompt_test_execution_contexts_execution_id"),
        "django_ai_prompt_test_execution_contexts",
        ["execution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_prompt_test_execution_contexts_test_automation_id"),
        "django_ai_prompt_test_execution_contexts",
        ["test_automation_id"],
        unique=False,
    )
    _recreate_shared_test_automation_table()
