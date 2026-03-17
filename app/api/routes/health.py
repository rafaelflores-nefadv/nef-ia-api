from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette import status

from app.schemas.health import HealthStatus, ReadinessStatus
from app.services.health_service import build_readiness_checks

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=ReadinessStatus)
async def health() -> ReadinessStatus:
    checks = await build_readiness_checks()
    status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    return ReadinessStatus(status=status, checks=checks)


@router.get("/live", response_model=HealthStatus)
async def liveness() -> HealthStatus:
    return HealthStatus(status="ok", service="nef-ia-api")


@router.get("/ready", response_model=ReadinessStatus)
async def readiness() -> ReadinessStatus:
    checks = await build_readiness_checks()
    ready = all(value == "ok" for value in checks.values())
    payload = ReadinessStatus(status="ok" if ready else "not_ready", checks=checks)
    return JSONResponse(
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload.model_dump(),
    )
