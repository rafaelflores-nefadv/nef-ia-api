"""API route modules."""

from . import (
    admin_auth,
    admin_catalog,
    admin_automation_execution,
    admin_execution_files,
    admin_execution_profiles,
    admin_metrics,
    admin_prompt_tests,
    admin_tokens,
    executions,
    external_catalog,
    external_executions,
    files,
    health,
    system,
)

__all__ = [
    "health",
    "system",
    "admin_auth",
    "admin_tokens",
    "admin_catalog",
    "admin_automation_execution",
    "admin_execution_profiles",
    "admin_prompt_tests",
    "admin_metrics",
    "external_catalog",
    "external_executions",
    "executions",
    "files",
    "admin_execution_files",
]
