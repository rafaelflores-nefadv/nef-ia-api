"""initial django ai operational schema

Revision ID: 20260316_0001
Revises:
Create Date: 2026-03-16 17:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260316_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "django_ai_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("access_level", sa.Integer(), nullable=False),
        *_timestamp_columns(),
        sa.CheckConstraint("access_level >= 0", name="ck_django_ai_roles_access_level_positive"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_roles")),
        sa.UniqueConstraint("name", name=op.f("uq_django_ai_roles_name")),
    )
    op.create_index(op.f("ix_django_ai_roles_name"), "django_ai_roles", ["name"], unique=False)

    op.create_table(
        "django_ai_providers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_providers")),
        sa.UniqueConstraint("slug", name=op.f("uq_django_ai_providers_slug")),
    )
    op.create_index(op.f("ix_django_ai_providers_slug"), "django_ai_providers", ["slug"], unique=False)

    op.create_table(
        "django_ai_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["role_id"], ["django_ai_roles.id"], ondelete="RESTRICT", name=op.f("fk_django_ai_users_role_id_django_ai_roles")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_users")),
        sa.UniqueConstraint("email", name=op.f("uq_django_ai_users_email")),
    )
    op.create_index(op.f("ix_django_ai_users_email"), "django_ai_users", ["email"], unique=False)
    op.create_index(op.f("ix_django_ai_users_role_id"), "django_ai_users", ["role_id"], unique=False)

    op.create_table(
        "django_ai_provider_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_name", sa.String(length=120), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["django_ai_providers.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_provider_credentials_provider_id_django_ai_providers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_provider_credentials")),
        sa.UniqueConstraint(
            "provider_id",
            "credential_name",
            name="uq_django_ai_provider_credentials_name",
        ),
    )
    op.create_index(
        op.f("ix_django_ai_provider_credentials_provider_id"),
        "django_ai_provider_credentials",
        ["provider_id"],
        unique=False,
    )

    op.create_table(
        "django_ai_provider_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("model_slug", sa.String(length=120), nullable=False),
        sa.Column("context_limit", sa.Integer(), nullable=False),
        sa.Column("cost_input_per_1k_tokens", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("cost_output_per_1k_tokens", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamp_columns(),
        sa.CheckConstraint("context_limit > 0", name="ck_django_ai_provider_models_context_limit"),
        sa.CheckConstraint(
            "cost_input_per_1k_tokens >= 0",
            name="ck_django_ai_provider_models_cost_input_nonnegative",
        ),
        sa.CheckConstraint(
            "cost_output_per_1k_tokens >= 0",
            name="ck_django_ai_provider_models_cost_output_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["django_ai_providers.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_provider_models_provider_id_django_ai_providers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_provider_models")),
        sa.UniqueConstraint(
            "provider_id",
            "model_slug",
            name="uq_django_ai_provider_models_provider_slug",
        ),
    )
    op.create_index(
        op.f("ix_django_ai_provider_models_provider_id"),
        "django_ai_provider_models",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_provider_models_model_slug"),
        "django_ai_provider_models",
        ["model_slug"],
        unique=False,
    )

    op.create_table(
        "django_ai_provider_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initial_credit", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("used_credit", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("current_balance", sa.Numeric(precision=18, scale=6), nullable=False),
        *_timestamp_columns(),
        sa.CheckConstraint("initial_credit >= 0", name="ck_django_ai_provider_balances_initial_credit"),
        sa.CheckConstraint("used_credit >= 0", name="ck_django_ai_provider_balances_used_credit"),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["django_ai_providers.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_provider_balances_provider_id_django_ai_providers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_provider_balances")),
        sa.UniqueConstraint("provider_id", name="uq_django_ai_provider_balances_provider_id"),
    )
    op.create_index(
        op.f("ix_django_ai_provider_balances_provider_id"),
        "django_ai_provider_balances",
        ["provider_id"],
        unique=False,
    )

    op.create_table(
        "django_ai_api_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["django_ai_users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_django_ai_api_tokens_created_by_user_id_django_ai_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_django_ai_api_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_django_ai_api_tokens_token_hash"),
        "django_ai_api_tokens",
        ["token_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_api_tokens_created_by_user_id"),
        "django_ai_api_tokens",
        ["created_by_user_id"],
        unique=False,
    )

    op.create_table(
        "django_ai_api_token_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("allow_execution", sa.Boolean(), nullable=False),
        sa.Column("allow_file_upload", sa.Boolean(), nullable=False),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["django_ai_api_tokens.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_api_token_permissions_token_id_django_ai_api_tokens"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["django_ai_providers.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_api_token_permissions_provider_id_django_ai_providers"),
        ),
        sa.ForeignKeyConstraint(
            ["automation_id"],
            ["automations.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_api_token_permissions_automation_id_automations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_api_token_permissions")),
        sa.UniqueConstraint(
            "token_id",
            "automation_id",
            "provider_id",
            name="uq_django_ai_api_token_permissions_scope",
        ),
    )
    op.create_index(
        op.f("ix_django_ai_api_token_permissions_token_id"),
        "django_ai_api_token_permissions",
        ["token_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_api_token_permissions_automation_id"),
        "django_ai_api_token_permissions",
        ["automation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_django_ai_api_token_permissions_provider_id"),
        "django_ai_api_token_permissions",
        ["provider_id"],
        unique=False,
    )

    op.create_table(
        "django_ai_api_token_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint("status_code >= 100", name="ck_django_ai_api_token_logs_status_code_min"),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["django_ai_api_tokens.id"],
            ondelete="SET NULL",
            name=op.f("fk_django_ai_api_token_logs_token_id_django_ai_api_tokens"),
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["analysis_executions.id"],
            ondelete="SET NULL",
            name=op.f("fk_django_ai_api_token_logs_execution_id_analysis_executions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_api_token_logs")),
    )
    op.create_index(op.f("ix_django_ai_api_token_logs_token_id"), "django_ai_api_token_logs", ["token_id"], unique=False)
    op.create_index(op.f("ix_django_ai_api_token_logs_execution_id"), "django_ai_api_token_logs", ["execution_id"], unique=False)
    op.create_index(op.f("ix_django_ai_api_token_logs_endpoint"), "django_ai_api_token_logs", ["endpoint"], unique=False)

    op.create_table(
        "django_ai_provider_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(precision=18, scale=6), nullable=False),
        *_timestamp_columns(),
        sa.CheckConstraint("estimated_cost >= 0", name="ck_django_ai_provider_usage_cost_nonnegative"),
        sa.CheckConstraint("input_tokens >= 0", name="ck_django_ai_provider_usage_input_tokens_nonnegative"),
        sa.CheckConstraint("output_tokens >= 0", name="ck_django_ai_provider_usage_output_tokens_nonnegative"),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["django_ai_providers.id"],
            ondelete="RESTRICT",
            name=op.f("fk_django_ai_provider_usage_provider_id_django_ai_providers"),
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["django_ai_provider_models.id"],
            ondelete="RESTRICT",
            name=op.f("fk_django_ai_provider_usage_model_id_django_ai_provider_models"),
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["analysis_executions.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_provider_usage_execution_id_analysis_executions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_provider_usage")),
    )
    op.create_index(op.f("ix_django_ai_provider_usage_provider_id"), "django_ai_provider_usage", ["provider_id"], unique=False)
    op.create_index(op.f("ix_django_ai_provider_usage_model_id"), "django_ai_provider_usage", ["model_id"], unique=False)
    op.create_index(op.f("ix_django_ai_provider_usage_execution_id"), "django_ai_provider_usage", ["execution_id"], unique=False)

    op.create_table(
        "django_ai_request_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamp_columns(),
        sa.CheckConstraint("file_size >= 0", name="ck_django_ai_request_files_size_nonnegative"),
        sa.ForeignKeyConstraint(
            ["analysis_request_id"],
            ["analysis_requests.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_request_files_analysis_request_id_analysis_requests"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_request_files")),
    )
    op.create_index(op.f("ix_django_ai_request_files_analysis_request_id"), "django_ai_request_files", ["analysis_request_id"], unique=False)
    op.create_index(op.f("ix_django_ai_request_files_checksum"), "django_ai_request_files", ["checksum"], unique=False)

    op.create_table(
        "django_ai_execution_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_type", sa.String(length=80), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint("file_size >= 0", name="ck_django_ai_execution_files_size_nonnegative"),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["analysis_executions.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_execution_files_execution_id_analysis_executions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_execution_files")),
    )
    op.create_index(op.f("ix_django_ai_execution_files_execution_id"), "django_ai_execution_files", ["execution_id"], unique=False)
    op.create_index(op.f("ix_django_ai_execution_files_file_type"), "django_ai_execution_files", ["file_type"], unique=False)

    op.create_table(
        "django_ai_queue_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_status", sa.String(length=32), nullable=False),
        sa.Column("worker_name", sa.String(length=120), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint("retry_count >= 0", name="ck_django_ai_queue_jobs_retry_count_nonnegative"),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["analysis_executions.id"],
            ondelete="CASCADE",
            name=op.f("fk_django_ai_queue_jobs_execution_id_analysis_executions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_queue_jobs")),
    )
    op.create_index(op.f("ix_django_ai_queue_jobs_execution_id"), "django_ai_queue_jobs", ["execution_id"], unique=False)
    op.create_index(op.f("ix_django_ai_queue_jobs_job_status"), "django_ai_queue_jobs", ["job_status"], unique=False)
    op.create_index(op.f("ix_django_ai_queue_jobs_worker_name"), "django_ai_queue_jobs", ["worker_name"], unique=False)

    op.create_table(
        "django_ai_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("performed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["performed_by_user_id"],
            ["django_ai_users.id"],
            ondelete="SET NULL",
            name=op.f("fk_django_ai_audit_logs_performed_by_user_id_django_ai_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_django_ai_audit_logs")),
    )
    op.create_index(op.f("ix_django_ai_audit_logs_action_type"), "django_ai_audit_logs", ["action_type"], unique=False)
    op.create_index(op.f("ix_django_ai_audit_logs_entity_type"), "django_ai_audit_logs", ["entity_type"], unique=False)
    op.create_index(op.f("ix_django_ai_audit_logs_entity_id"), "django_ai_audit_logs", ["entity_id"], unique=False)
    op.create_index(
        op.f("ix_django_ai_audit_logs_performed_by_user_id"),
        "django_ai_audit_logs",
        ["performed_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_django_ai_audit_logs_performed_by_user_id"), table_name="django_ai_audit_logs")
    op.drop_index(op.f("ix_django_ai_audit_logs_entity_id"), table_name="django_ai_audit_logs")
    op.drop_index(op.f("ix_django_ai_audit_logs_entity_type"), table_name="django_ai_audit_logs")
    op.drop_index(op.f("ix_django_ai_audit_logs_action_type"), table_name="django_ai_audit_logs")
    op.drop_table("django_ai_audit_logs")

    op.drop_index(op.f("ix_django_ai_queue_jobs_worker_name"), table_name="django_ai_queue_jobs")
    op.drop_index(op.f("ix_django_ai_queue_jobs_job_status"), table_name="django_ai_queue_jobs")
    op.drop_index(op.f("ix_django_ai_queue_jobs_execution_id"), table_name="django_ai_queue_jobs")
    op.drop_table("django_ai_queue_jobs")

    op.drop_index(op.f("ix_django_ai_execution_files_file_type"), table_name="django_ai_execution_files")
    op.drop_index(op.f("ix_django_ai_execution_files_execution_id"), table_name="django_ai_execution_files")
    op.drop_table("django_ai_execution_files")

    op.drop_index(op.f("ix_django_ai_request_files_checksum"), table_name="django_ai_request_files")
    op.drop_index(op.f("ix_django_ai_request_files_analysis_request_id"), table_name="django_ai_request_files")
    op.drop_table("django_ai_request_files")

    op.drop_index(op.f("ix_django_ai_provider_usage_execution_id"), table_name="django_ai_provider_usage")
    op.drop_index(op.f("ix_django_ai_provider_usage_model_id"), table_name="django_ai_provider_usage")
    op.drop_index(op.f("ix_django_ai_provider_usage_provider_id"), table_name="django_ai_provider_usage")
    op.drop_table("django_ai_provider_usage")

    op.drop_index(op.f("ix_django_ai_api_token_logs_endpoint"), table_name="django_ai_api_token_logs")
    op.drop_index(op.f("ix_django_ai_api_token_logs_execution_id"), table_name="django_ai_api_token_logs")
    op.drop_index(op.f("ix_django_ai_api_token_logs_token_id"), table_name="django_ai_api_token_logs")
    op.drop_table("django_ai_api_token_logs")

    op.drop_index(op.f("ix_django_ai_api_token_permissions_provider_id"), table_name="django_ai_api_token_permissions")
    op.drop_index(op.f("ix_django_ai_api_token_permissions_automation_id"), table_name="django_ai_api_token_permissions")
    op.drop_index(op.f("ix_django_ai_api_token_permissions_token_id"), table_name="django_ai_api_token_permissions")
    op.drop_table("django_ai_api_token_permissions")

    op.drop_index(op.f("ix_django_ai_api_tokens_created_by_user_id"), table_name="django_ai_api_tokens")
    op.drop_index(op.f("ix_django_ai_api_tokens_token_hash"), table_name="django_ai_api_tokens")
    op.drop_table("django_ai_api_tokens")

    op.drop_index(op.f("ix_django_ai_provider_balances_provider_id"), table_name="django_ai_provider_balances")
    op.drop_table("django_ai_provider_balances")

    op.drop_index(op.f("ix_django_ai_provider_models_model_slug"), table_name="django_ai_provider_models")
    op.drop_index(op.f("ix_django_ai_provider_models_provider_id"), table_name="django_ai_provider_models")
    op.drop_table("django_ai_provider_models")

    op.drop_index(op.f("ix_django_ai_provider_credentials_provider_id"), table_name="django_ai_provider_credentials")
    op.drop_table("django_ai_provider_credentials")

    op.drop_index(op.f("ix_django_ai_users_role_id"), table_name="django_ai_users")
    op.drop_index(op.f("ix_django_ai_users_email"), table_name="django_ai_users")
    op.drop_table("django_ai_users")

    op.drop_index(op.f("ix_django_ai_providers_slug"), table_name="django_ai_providers")
    op.drop_table("django_ai_providers")

    op.drop_index(op.f("ix_django_ai_roles_name"), table_name="django_ai_roles")
    op.drop_table("django_ai_roles")

