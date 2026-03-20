"""add persisted execution settings per automation

Revision ID: 20260320_0004
Revises: 20260320_0003
Create Date: 2026-03-20 18:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260320_0004"
down_revision: Union[str, Sequence[str], None] = "20260320_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "django_ai_automation_execution_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_profile", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("max_execution_rows", sa.Integer(), nullable=True),
        sa.Column("max_provider_calls", sa.Integer(), nullable=True),
        sa.Column("max_text_chunks", sa.Integer(), nullable=True),
        sa.Column("max_tabular_row_characters", sa.Integer(), nullable=True),
        sa.Column("max_execution_seconds", sa.Integer(), nullable=True),
        sa.Column("max_context_characters", sa.Integer(), nullable=True),
        sa.Column("max_context_file_characters", sa.Integer(), nullable=True),
        sa.Column("max_prompt_characters", sa.Integer(), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint(
            "execution_profile IN ('standard', 'heavy', 'extended')",
            name="ck_django_ai_automation_execution_settings_profile_valid",
        ),
        sa.CheckConstraint(
            "max_execution_rows IS NULL OR max_execution_rows > 0",
            name="ck_django_ai_automation_execution_settings_max_execution_rows_positive",
        ),
        sa.CheckConstraint(
            "max_provider_calls IS NULL OR max_provider_calls > 0",
            name="ck_django_ai_automation_execution_settings_max_provider_calls_positive",
        ),
        sa.CheckConstraint(
            "max_text_chunks IS NULL OR max_text_chunks > 0",
            name="ck_django_ai_automation_execution_settings_max_text_chunks_positive",
        ),
        sa.CheckConstraint(
            "max_tabular_row_characters IS NULL OR max_tabular_row_characters > 0",
            name="ck_django_ai_automation_execution_settings_max_tabular_row_characters_positive",
        ),
        sa.CheckConstraint(
            "max_execution_seconds IS NULL OR max_execution_seconds > 0",
            name="ck_django_ai_automation_execution_settings_max_execution_seconds_positive",
        ),
        sa.CheckConstraint(
            "max_context_characters IS NULL OR max_context_characters > 0",
            name="ck_django_ai_automation_execution_settings_max_context_characters_positive",
        ),
        sa.CheckConstraint(
            "max_context_file_characters IS NULL OR max_context_file_characters > 0",
            name="ck_django_ai_automation_execution_settings_max_context_file_characters_positive",
        ),
        sa.CheckConstraint(
            "max_prompt_characters IS NULL OR max_prompt_characters > 0",
            name="ck_django_ai_automation_execution_settings_max_prompt_characters_positive",
        ),
        sa.ForeignKeyConstraint(
            ["automation_id"],
            ["automations.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_automation_execution_settings_automation_id_automations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_automation_execution_settings")),
        sa.UniqueConstraint(
            "automation_id",
            name="uq_django_ai_automation_execution_settings_automation_id",
        ),
    )
    op.create_index(
        op.f("ix_django_ai_automation_execution_settings_automation_id"),
        "django_ai_automation_execution_settings",
        ["automation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_automation_execution_settings_execution_profile"),
        "django_ai_automation_execution_settings",
        ["execution_profile"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_automation_execution_settings_is_active"),
        "django_ai_automation_execution_settings",
        ["is_active"],
        unique=False,
    )
    op.alter_column("django_ai_automation_execution_settings", "is_active", server_default=None)


def downgrade() -> None:
    op.drop_index(
        op.f("ix_django_ai_automation_execution_settings_is_active"),
        table_name="django_ai_automation_execution_settings",
    )
    op.drop_index(
        op.f("ix_django_ai_automation_execution_settings_execution_profile"),
        table_name="django_ai_automation_execution_settings",
    )
    op.drop_index(
        op.f("ix_django_ai_automation_execution_settings_automation_id"),
        table_name="django_ai_automation_execution_settings",
    )
    op.drop_table("django_ai_automation_execution_settings")
