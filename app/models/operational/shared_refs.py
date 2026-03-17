from sqlalchemy import Column, Table
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import OperationalBase

# Shared-system tables are source-of-truth in the general app.
# These proxy declarations exist only to support FK resolution in operational models.
# Alembic excludes them from migration generation.
Table(
    "automations",
    OperationalBase.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    info={"skip_autogenerate": True, "shared_reference": True},
)

Table(
    "automation_prompts",
    OperationalBase.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    info={"skip_autogenerate": True, "shared_reference": True},
)

Table(
    "analysis_requests",
    OperationalBase.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    info={"skip_autogenerate": True, "shared_reference": True},
)

Table(
    "analysis_executions",
    OperationalBase.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    info={"skip_autogenerate": True, "shared_reference": True},
)

