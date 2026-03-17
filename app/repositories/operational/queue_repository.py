from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func, select, update

from app.models.operational import DjangoAiQueueJob


class QueueJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: DjangoAiQueueJob) -> DjangoAiQueueJob:
        self.session.add(job)
        self.session.flush()
        return job

    def get_by_id(self, job_id: UUID) -> DjangoAiQueueJob | None:
        stmt = select(DjangoAiQueueJob).where(DjangoAiQueueJob.id == job_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_latest_by_execution_id(self, execution_id: UUID) -> DjangoAiQueueJob | None:
        stmt = (
            select(DjangoAiQueueJob)
            .where(DjangoAiQueueJob.execution_id == execution_id)
            .order_by(DjangoAiQueueJob.created_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_execution_id(self, execution_id: UUID) -> list[DjangoAiQueueJob]:
        stmt = (
            select(DjangoAiQueueJob)
            .where(DjangoAiQueueJob.execution_id == execution_id)
            .order_by(DjangoAiQueueJob.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def has_active_job_for_execution(self, execution_id: UUID) -> bool:
        stmt = select(func.count(DjangoAiQueueJob.id)).where(
            DjangoAiQueueJob.execution_id == execution_id,
            DjangoAiQueueJob.job_status.in_(("pending", "queued", "processing", "generating_output")),
        )
        count = self.session.execute(stmt).scalar_one()
        return bool(count)

    def acquire_for_processing(self, *, queue_job_id: UUID, worker_name: str, started_at) -> bool:  # type: ignore[no-untyped-def]
        stmt = (
            update(DjangoAiQueueJob)
            .where(
                DjangoAiQueueJob.id == queue_job_id,
                DjangoAiQueueJob.job_status.in_(("queued", "pending")),
            )
            .values(
                job_status="processing",
                worker_name=worker_name,
                started_at=started_at,
                finished_at=None,
                error_message=None,
            )
        )
        result = self.session.execute(stmt)
        return bool(result.rowcount)

    def mark_queued_for_retry(
        self,
        *,
        queue_job_id: UUID,
        retry_count: int,
        error_message: str,
    ) -> bool:
        stmt = (
            update(DjangoAiQueueJob)
            .where(DjangoAiQueueJob.id == queue_job_id)
            .values(
                job_status="queued",
                retry_count=retry_count,
                error_message=error_message[:2000],
                started_at=None,
                finished_at=None,
            )
        )
        result = self.session.execute(stmt)
        return bool(result.rowcount)

    def count_processing_jobs(self, *, exclude_queue_job_id: UUID | None = None) -> int:
        filters = [
            DjangoAiQueueJob.job_status == "processing",
            DjangoAiQueueJob.started_at.is_not(None),
            DjangoAiQueueJob.finished_at.is_(None),
        ]
        if exclude_queue_job_id is not None:
            filters.append(DjangoAiQueueJob.id != exclude_queue_job_id)
        stmt = select(func.count(DjangoAiQueueJob.id)).where(*filters)
        return int(self.session.execute(stmt).scalar_one() or 0)
