import logging
from uuid import UUID

import dramatiq

from app.core.config import get_settings
from app.core.log_context import bind_log_context, reset_log_context
from app.db.session import SessionLocal
from app.db.shared_session import SharedSessionLocal
from app.services.execution_service import ExecutionService
from app.workers import execution_worker as _execution_worker  # noqa: F401

logger = logging.getLogger(__name__)
settings = get_settings()


@dramatiq.actor(max_retries=0, queue_name=settings.queue_name)
def process_execution_task(execution_id: str, queue_job_id: str, correlation_id: str | None = None) -> None:
    execution_uuid = UUID(execution_id)
    queue_job_uuid = UUID(queue_job_id)

    context_tokens = bind_log_context(
        correlation_id=correlation_id,
        request_id=correlation_id,
        execution_id=str(execution_uuid),
    )
    try:
        logger.info("Worker picked execution job.", extra={"execution_id": str(execution_uuid), "queue_job_id": str(queue_job_uuid)})
        with SessionLocal() as operational_session, SharedSessionLocal() as shared_session:
            service = ExecutionService(
                operational_session=operational_session,
                shared_session=shared_session,
            )
            service.process_execution_job(
                execution_id=execution_uuid,
                queue_job_id=queue_job_uuid,
                worker_name="dramatiq-worker",
                correlation_id=correlation_id,
            )
    finally:
        reset_log_context(context_tokens)
