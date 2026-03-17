"""API route modules."""

from . import admin_auth, admin_catalog, admin_execution_files, admin_metrics, admin_tokens, files, health, system

__all__ = [
    "health",
    "system",
    "admin_auth",
    "admin_tokens",
    "admin_catalog",
    "admin_metrics",
    "files",
    "admin_execution_files",
]
