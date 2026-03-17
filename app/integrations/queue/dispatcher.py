import logging
from uuid import UUID

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def enqueue_execution_job(
    *,
    execution_id: UUID,
    queue_job_id: UUID,
    correlation_id: str | None = None,
    delay_ms: int | None = None,
) -> None:
    if settings.queue_backend == "none":
        logger.warning(
            "Queue backend is disabled; execution remained queued without dispatch.",
            extra={"execution_id": str(execution_id), "queue_job_id": str(queue_job_id)},
        )
        return

    if settings.queue_backend != "dramatiq":
        raise RuntimeError(f"Unsupported queue backend for execution dispatch: {settings.queue_backend}")

    from app.workers.tasks import process_execution_task

    if delay_ms and delay_ms > 0:
        process_execution_task.send_with_options(
            args=(str(execution_id), str(queue_job_id), correlation_id),
            delay=delay_ms,
        )
    else:
        process_execution_task.send(str(execution_id), str(queue_job_id), correlation_id)
    logger.info(
        "Execution job dispatched to Dramatiq.",
        extra={"execution_id": str(execution_id), "queue_job_id": str(queue_job_id)},
    )
