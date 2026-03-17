import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import dispose_operational_engine
from app.db.shared_session import dispose_shared_engine
from app.integrations.queue.redis_client import close_redis_client
from app.integrations.storage.local_storage import ensure_storage_root
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.token_auth import TokenAuthMiddleware

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Application startup initiated.", extra={"environment": settings.app_env})
    ensure_storage_root()
    logger.info("Storage path ready.", extra={"storage_path": settings.storage_path})
    yield
    logger.info("Application shutdown initiated.")
    await close_redis_client()
    dispose_operational_engine()
    dispose_shared_engine()
    logger.info("Resources disposed. Shutdown complete.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        debug=settings.app_debug,
        lifespan=lifespan,
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TokenAuthMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    app.include_router(api_router)
    register_exception_handlers(app)
    return app


app = create_app()
