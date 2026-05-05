"""add execution explanations table

Revision ID: 20260505_0014
Revises: 20260323_0013
Create Date: 2026-05-05 17:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260505_0014"
down_revision: Union[str, Sequence[str], None] = "20260323_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "django_ai_execution_explanations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("simple_explanation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["analysis_executions.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_execution_explanations_execution_id_analysis_executions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_execution_explanations")),
        sa.UniqueConstraint("execution_id", name="uq_django_ai_execution_explanations_execution_id"),
    )
    op.create_index(
        op.f("ix_django_ai_execution_explanations_execution_id"),
        "django_ai_execution_explanations",
        ["execution_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_django_ai_execution_explanations_execution_id"),
        table_name="django_ai_execution_explanations",
    )
    op.drop_table("django_ai_execution_explanations")
