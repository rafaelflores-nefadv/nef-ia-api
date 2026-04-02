from fastapi import APIRouter

from app.api.routes import (
    admin_automation_execution,
    admin_auth,
    admin_catalog,
    admin_execution_files,
    admin_execution_profiles,
    admin_metrics,
    admin_prompt_tests,
    admin_tokens,
    executions,
    external_assistants,
    external_catalog,
    external_executions,
    files,
    health,
    system,
)
from app.core.config import get_settings

settings = get_settings()

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router, prefix=f"{settings.api_prefix}/system")
api_router.include_router(admin_auth.router, prefix=f"{settings.api_prefix}/admin")
api_router.include_router(admin_tokens.router, prefix=f"{settings.api_prefix}/admin")
api_router.include_router(admin_catalog.router, prefix=f"{settings.api_prefix}/admin")
api_router.include_router(admin_automation_execution.router, prefix=f"{settings.api_prefix}/admin")
api_router.include_router(admin_execution_files.router, prefix=f"{settings.api_prefix}/admin")
api_router.include_router(admin_execution_profiles.router, prefix=f"{settings.api_prefix}/admin")
api_router.include_router(admin_metrics.router, prefix=f"{settings.api_prefix}/admin")
api_router.include_router(admin_prompt_tests.router, prefix=f"{settings.api_prefix}/admin")
api_router.include_router(files.router)
api_router.include_router(executions.router)
api_router.include_router(external_executions.router)
api_router.include_router(external_catalog.router)
api_router.include_router(external_assistants.router)
