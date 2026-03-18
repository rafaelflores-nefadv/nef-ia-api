"""add integration tokens

Revision ID: 20260318_0002
Revises: 20260316_0001
Create Date: 2026-03-18 22:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260318_0002"
down_revision: Union[str, Sequence[str], None] = "20260316_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "django_ai_integration_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["django_ai_users.id"],
            name=op.f("fk_django_ai_integration_tokens_created_by_user_id_django_ai_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_integration_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_django_ai_integration_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_django_ai_integration_tokens_token_hash"),
        "django_ai_integration_tokens",
        ["token_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_integration_tokens_created_by_user_id"),
        "django_ai_integration_tokens",
        ["created_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_django_ai_integration_tokens_created_by_user_id"),
        table_name="django_ai_integration_tokens",
    )
    op.drop_index(op.f("ix_django_ai_integration_tokens_token_hash"), table_name="django_ai_integration_tokens")
    op.drop_table("django_ai_integration_tokens")
