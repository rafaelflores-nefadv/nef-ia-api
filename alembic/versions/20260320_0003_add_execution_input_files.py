"""add execution input files linkage table

Revision ID: 20260320_0003
Revises: 20260316_0003, 20260318_0002
Create Date: 2026-03-20 14:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260320_0003"
down_revision: Union[str, Sequence[str], None] = ("20260316_0003", "20260318_0002")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "django_ai_execution_input_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        *_timestamp_columns(),
        sa.CheckConstraint(
            "role IN ('primary', 'context')",
            name="ck_django_ai_execution_input_files_role_valid",
        ),
        sa.CheckConstraint(
            "order_index >= 0",
            name="ck_django_ai_execution_input_files_order_index_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["analysis_executions.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_execution_input_files_execution_id_analysis_executions"),
        ),
        sa.ForeignKeyConstraint(
            ["request_file_id"],
            ["django_ai_request_files.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_execution_input_files_request_file_id_django_ai_request_files"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_execution_input_files")),
        sa.UniqueConstraint(
            "execution_id",
            "request_file_id",
            name="uq_django_ai_execution_input_files_execution_request",
        ),
    )
    op.create_index(
        op.f("ix_django_ai_execution_input_files_execution_id"),
        "django_ai_execution_input_files",
        ["execution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_execution_input_files_request_file_id"),
        "django_ai_execution_input_files",
        ["request_file_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_execution_input_files_role"),
        "django_ai_execution_input_files",
        ["role"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_execution_input_files_order_index"),
        "django_ai_execution_input_files",
        ["order_index"],
        unique=False,
    )
    op.alter_column("django_ai_execution_input_files", "order_index", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_django_ai_execution_input_files_order_index"), table_name="django_ai_execution_input_files")
    op.drop_index(op.f("ix_django_ai_execution_input_files_role"), table_name="django_ai_execution_input_files")
    op.drop_index(op.f("ix_django_ai_execution_input_files_request_file_id"), table_name="django_ai_execution_input_files")
    op.drop_index(op.f("ix_django_ai_execution_input_files_execution_id"), table_name="django_ai_execution_input_files")
    op.drop_table("django_ai_execution_input_files")
