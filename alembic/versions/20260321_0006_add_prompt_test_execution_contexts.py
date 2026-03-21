"""add prompt test execution contexts

Revision ID: 20260321_0006
Revises: 20260320_0005
Create Date: 2026-03-21 00:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260321_0006"
down_revision: Union[str, Sequence[str], None] = "20260320_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index(
        op.f("ix_django_ai_prompt_test_execution_contexts_test_automation_id"),
        table_name="django_ai_prompt_test_execution_contexts",
    )
    op.drop_index(
        op.f("ix_django_ai_prompt_test_execution_contexts_execution_id"),
        table_name="django_ai_prompt_test_execution_contexts",
    )
    op.drop_table("django_ai_prompt_test_execution_contexts")
