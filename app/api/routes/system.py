from fastapi import APIRouter, Depends

from app.api.dependencies.security import get_current_token
from app.core.config import get_settings
from app.models.operational import DjangoAiApiToken
from app.schemas.system import SystemInfoResponse

settings = get_settings()
router = APIRouter(tags=["system"])


@router.get("/info", response_model=SystemInfoResponse)
async def system_info(_: DjangoAiApiToken = Depends(get_current_token)) -> SystemInfoResponse:
    return SystemInfoResponse(
        app_name=settings.app_name,
        environment=settings.app_env,
        api_prefix=settings.api_prefix,
        queue_backend=settings.queue_backend,
        storage_path=settings.storage_path,
    )
