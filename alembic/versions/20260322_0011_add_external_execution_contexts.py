"""add external execution contexts scoped by api token

Revision ID: 20260322_0011
Revises: 20260322_0010
Create Date: 2026-03-22 18:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260322_0011"
down_revision: Union[str, Sequence[str], None] = "20260322_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "django_ai_external_execution_contexts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.String(length=20), nullable=False),
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "resource_type IN ('prompt', 'automation')",
            name="ck_django_ai_external_execution_contexts_resource_type_valid",
        ),
        sa.CheckConstraint(
            "("
            "(resource_type = 'prompt' AND prompt_id IS NOT NULL)"
            " OR "
            "(resource_type = 'automation' AND prompt_id IS NULL)"
            ")",
            name="ck_django_ai_external_execution_contexts_prompt_scope_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["analysis_executions.id"],
            name=op.f("fk_django_ai_external_execution_contexts_execution_id_analysis_executions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["django_ai_api_tokens.id"],
            name=op.f("fk_django_ai_external_execution_contexts_token_id_django_ai_api_tokens"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_external_execution_contexts")),
        sa.UniqueConstraint("execution_id", name=op.f("uq_django_ai_external_execution_contexts_execution_id")),
    )
    op.create_index(
        op.f("ix_django_ai_external_execution_contexts_token_id_resource_type_created_at"),
        "django_ai_external_execution_contexts",
        ["token_id", "resource_type", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_external_execution_contexts_token_id_prompt_id"),
        "django_ai_external_execution_contexts",
        ["token_id", "prompt_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_external_execution_contexts_token_id_automation_id"),
        "django_ai_external_execution_contexts",
        ["token_id", "automation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_external_execution_contexts_analysis_request_id"),
        "django_ai_external_execution_contexts",
        ["analysis_request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_django_ai_external_execution_contexts_analysis_request_id"),
        table_name="django_ai_external_execution_contexts",
    )
    op.drop_index(
        op.f("ix_django_ai_external_execution_contexts_token_id_automation_id"),
        table_name="django_ai_external_execution_contexts",
    )
    op.drop_index(
        op.f("ix_django_ai_external_execution_contexts_token_id_prompt_id"),
        table_name="django_ai_external_execution_contexts",
    )
    op.drop_index(
        op.f("ix_django_ai_external_execution_contexts_token_id_resource_type_created_at"),
        table_name="django_ai_external_execution_contexts",
    )
    op.drop_table("django_ai_external_execution_contexts")
