"""add prompt override field to queue jobs

Revision ID: 20260320_0005
Revises: 20260320_0004
Create Date: 2026-03-20 23:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260320_0005"
down_revision: Union[str, Sequence[str], None] = "20260320_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "django_ai_queue_jobs",
        sa.Column("prompt_override_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("django_ai_queue_jobs", "prompt_override_text")

