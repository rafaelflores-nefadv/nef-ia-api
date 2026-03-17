"""add file_name and checksum to django_ai_execution_files

Revision ID: 20260316_0002
Revises: 20260316_0001
Create Date: 2026-03-16 19:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260316_0002"
down_revision: Union[str, Sequence[str], None] = "20260316_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "django_ai_execution_files",
        sa.Column("file_name", sa.String(length=255), nullable=False, server_default="generated_file"),
    )
    op.add_column("django_ai_execution_files", sa.Column("checksum", sa.String(length=128), nullable=True))
    op.create_index(op.f("ix_django_ai_execution_files_checksum"), "django_ai_execution_files", ["checksum"], unique=False)
    op.alter_column("django_ai_execution_files", "file_name", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_django_ai_execution_files_checksum"), table_name="django_ai_execution_files")
    op.drop_column("django_ai_execution_files", "checksum")
    op.drop_column("django_ai_execution_files", "file_name")

