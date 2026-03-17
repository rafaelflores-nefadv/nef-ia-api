from app.core.config import get_settings
from app.db.session import check_operational_database
from app.db.session import SessionLocal
from app.db.shared_session import check_shared_database
from app.integrations.queue.redis_client import check_redis_connection
from app.repositories.operational import ProviderModelRepository, ProviderRepository

settings = get_settings()


def _check_queue_backend_configured() -> bool:
    return settings.queue_backend in {"dramatiq", "celery"}


def _check_provider_configuration() -> bool:
    with SessionLocal() as session:
        provider_repo = ProviderRepository(session)
        model_repo = ProviderModelRepository(session)
        providers = provider_repo.list_active()
        for provider in providers:
            credential = provider_repo.get_active_credential(provider.id)
            if credential is None:
                continue
            if model_repo.exists_active_for_provider(provider.id):
                return True
        return False


async def build_readiness_checks() -> dict[str, str]:
    checks: dict[str, str] = {}

    try:
        check_operational_database()
        checks["database_operational"] = "ok"
    except Exception:
        checks["database_operational"] = "error"

    try:
        check_shared_database()
        checks["database_shared"] = "ok"
    except Exception:
        checks["database_shared"] = "error"

    try:
        await check_redis_connection()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    try:
        checks["queue"] = "ok" if _check_queue_backend_configured() else "error"
    except Exception:
        checks["queue"] = "error"

    try:
        checks["provider_configured"] = "ok" if _check_provider_configuration() else "error"
    except Exception:
        checks["provider_configured"] = "error"

    return checks
