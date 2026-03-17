"""add request_file_id to django_ai_queue_jobs

Revision ID: 20260316_0003
Revises: 20260316_0002
Create Date: 2026-03-16 21:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260316_0003"
down_revision: Union[str, Sequence[str], None] = "20260316_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "django_ai_queue_jobs",
        sa.Column("request_file_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(op.f("ix_django_ai_queue_jobs_request_file_id"), "django_ai_queue_jobs", ["request_file_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_django_ai_queue_jobs_request_file_id_django_ai_request_files"),
        "django_ai_queue_jobs",
        "django_ai_request_files",
        ["request_file_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_django_ai_queue_jobs_request_file_id_django_ai_request_files"),
        "django_ai_queue_jobs",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_django_ai_queue_jobs_request_file_id"), table_name="django_ai_queue_jobs")
    op.drop_column("django_ai_queue_jobs", "request_file_id")
