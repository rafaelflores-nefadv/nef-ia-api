from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class MetricsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _execution_filters(
        *,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
        status: str | None,
    ) -> tuple[str, dict[str, Any]]:
        clauses = ["1=1"]
        params: dict[str, Any] = {}
        if start_at is not None:
            clauses.append("e.created_at >= :start_at")
            params["start_at"] = start_at
        if end_at is not None:
            clauses.append("e.created_at <= :end_at")
            params["end_at"] = end_at
        if provider:
            clauses.append("p.slug = :provider")
            params["provider"] = provider
        if model:
            clauses.append("pm.model_slug = :model")
            params["model"] = model
        if automation_id:
            clauses.append("ar.automation_id::text = :automation_id")
            params["automation_id"] = automation_id
        if status:
            clauses.append("e.status = :execution_status")
            params["execution_status"] = status
        return " AND ".join(clauses), params

    def _filtered_executions_cte(
        self,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
        status: str | None,
    ) -> tuple[str, dict[str, Any]]:
        where_sql, params = self._execution_filters(
            start_at=start_at,
            end_at=end_at,
            provider=provider,
            model=model,
            automation_id=automation_id,
            status=status,
        )
        cte = f"""
            WITH latest_usage AS (
                SELECT DISTINCT ON (u.execution_id)
                    u.execution_id,
                    u.provider_id,
                    u.model_id,
                    u.input_tokens,
                    u.output_tokens,
                    u.estimated_cost,
                    u.created_at
                FROM django_ai_provider_usage u
                ORDER BY u.execution_id, u.created_at DESC
            ),
            filtered_executions AS (
                SELECT
                    e.id,
                    e.status,
                    e.analysis_request_id,
                    e.created_at,
                    ar.automation_id,
                    p.slug AS provider_slug,
                    pm.model_slug AS model_slug
                FROM analysis_executions e
                JOIN analysis_requests ar ON ar.id = e.analysis_request_id
                LEFT JOIN latest_usage lu ON lu.execution_id = e.id
                LEFT JOIN django_ai_providers p ON p.id = lu.provider_id
                LEFT JOIN django_ai_provider_models pm ON pm.id = lu.model_id
                WHERE {where_sql}
            )
        """
        return cte, params

    def execution_status_totals(
        self,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
        status: str | None,
    ) -> list[dict[str, Any]]:
        cte, params = self._filtered_executions_cte(
            start_at=start_at,
            end_at=end_at,
            provider=provider,
            model=model,
            automation_id=automation_id,
            status=status,
        )
        query = text(
            f"""
            {cte}
            SELECT fe.status, COUNT(*)::int AS total
            FROM filtered_executions fe
            GROUP BY fe.status
            ORDER BY fe.status
            """
        )
        rows = self.session.execute(query, params).mappings().all()
        return [dict(row) for row in rows]

    def execution_totals_by_day(
        self,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
        status: str | None,
    ) -> list[dict[str, Any]]:
        cte, params = self._filtered_executions_cte(
            start_at=start_at,
            end_at=end_at,
            provider=provider,
            model=model,
            automation_id=automation_id,
            status=status,
        )
        query = text(
            f"""
            {cte}
            SELECT date_trunc('day', fe.created_at) AS day, COUNT(*)::int AS total
            FROM filtered_executions fe
            GROUP BY day
            ORDER BY day
            """
        )
        rows = self.session.execute(query, params).mappings().all()
        return [dict(row) for row in rows]

    def average_execution_duration_seconds(
        self,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
        status: str | None,
    ) -> float:
        cte, params = self._filtered_executions_cte(
            start_at=start_at,
            end_at=end_at,
            provider=provider,
            model=model,
            automation_id=automation_id,
            status=status,
        )
        query = text(
            f"""
            {cte}
            SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (q.finished_at - q.started_at))), 0) AS avg_seconds
            FROM django_ai_queue_jobs q
            JOIN filtered_executions fe ON fe.id = q.execution_id
            WHERE q.started_at IS NOT NULL
              AND q.finished_at IS NOT NULL
            """
        )
        value = self.session.execute(query, params).scalar_one()
        return float(value or 0)

    def queue_status_totals(
        self,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
        status: str | None,
    ) -> list[dict[str, Any]]:
        cte, params = self._filtered_executions_cte(
            start_at=start_at,
            end_at=end_at,
            provider=provider,
            model=model,
            automation_id=automation_id,
            status=None,
        )
        queue_status_filter = ""
        if status:
            queue_status_filter = "AND q.job_status = :queue_status"
            params["queue_status"] = status

        query = text(
            f"""
            {cte}
            SELECT q.job_status, COUNT(*)::int AS total
            FROM django_ai_queue_jobs q
            JOIN filtered_executions fe ON fe.id = q.execution_id
            WHERE 1=1
              {queue_status_filter}
            GROUP BY q.job_status
            ORDER BY q.job_status
            """
        )
        rows = self.session.execute(query, params).mappings().all()
        return [dict(row) for row in rows]

    def queue_processing_stats(
        self,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
        status: str | None,
    ) -> dict[str, Any]:
        cte, params = self._filtered_executions_cte(
            start_at=start_at,
            end_at=end_at,
            provider=provider,
            model=model,
            automation_id=automation_id,
            status=None,
        )
        queue_status_filter = ""
        if status:
            queue_status_filter = "AND q.job_status = :queue_status"
            params["queue_status"] = status

        query = text(
            f"""
            {cte}
            SELECT
                COALESCE(AVG(EXTRACT(EPOCH FROM (q.finished_at - q.started_at))), 0) AS avg_processing_seconds,
                COALESCE(SUM(q.retry_count), 0)::int AS total_retries,
                COALESCE(
                    MAX(EXTRACT(EPOCH FROM (NOW() - q.created_at)))
                    FILTER (WHERE q.job_status IN ('queued', 'pending')),
                    0
                ) AS oldest_queued_age_seconds
            FROM django_ai_queue_jobs q
            JOIN filtered_executions fe ON fe.id = q.execution_id
            WHERE 1=1
              {queue_status_filter}
            """
        )
        row = self.session.execute(query, params).mappings().one()
        return dict(row)

    def usage_totals(
        self,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
        status: str | None,
    ) -> dict[str, Any]:
        clauses = ["1=1"]
        params: dict[str, Any] = {}
        if start_at is not None:
            clauses.append("u.created_at >= :start_at")
            params["start_at"] = start_at
        if end_at is not None:
            clauses.append("u.created_at <= :end_at")
            params["end_at"] = end_at
        if provider:
            clauses.append("p.slug = :provider")
            params["provider"] = provider
        if model:
            clauses.append("pm.model_slug = :model")
            params["model"] = model
        if automation_id:
            clauses.append("ar.automation_id::text = :automation_id")
            params["automation_id"] = automation_id
        if status:
            clauses.append("e.status = :execution_status")
            params["execution_status"] = status
        where_sql = " AND ".join(clauses)

        query = text(
            f"""
            SELECT
                COALESCE(SUM(u.input_tokens), 0)::bigint AS input_tokens,
                COALESCE(SUM(u.output_tokens), 0)::bigint AS output_tokens,
                COALESCE(SUM(u.estimated_cost), 0) AS total_cost,
                COUNT(*)::int AS usage_rows
            FROM django_ai_provider_usage u
            JOIN analysis_executions e ON e.id = u.execution_id
            JOIN analysis_requests ar ON ar.id = e.analysis_request_id
            JOIN django_ai_providers p ON p.id = u.provider_id
            JOIN django_ai_provider_models pm ON pm.id = u.model_id
            WHERE {where_sql}
            """
        )
        return dict(self.session.execute(query, params).mappings().one())

    def usage_by_provider(
        self,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
        status: str | None,
    ) -> list[dict[str, Any]]:
        return self._usage_group_by(
            group_sql="p.slug",
            alias_name="provider",
            start_at=start_at,
            end_at=end_at,
            provider=provider,
            model=model,
            automation_id=automation_id,
            status=status,
        )

    def usage_by_model(
        self,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
        status: str | None,
    ) -> list[dict[str, Any]]:
        return self._usage_group_by(
            group_sql="pm.model_slug",
            alias_name="model",
            start_at=start_at,
            end_at=end_at,
            provider=provider,
            model=model,
            automation_id=automation_id,
            status=status,
        )

    def usage_by_automation(
        self,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
        status: str | None,
    ) -> list[dict[str, Any]]:
        return self._usage_group_by(
            group_sql="ar.automation_id::text",
            alias_name="automation_id",
            start_at=start_at,
            end_at=end_at,
            provider=provider,
            model=model,
            automation_id=automation_id,
            status=status,
        )

    def _usage_group_by(
        self,
        *,
        group_sql: str,
        alias_name: str,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
        status: str | None,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        params: dict[str, Any] = {}
        if start_at is not None:
            clauses.append("u.created_at >= :start_at")
            params["start_at"] = start_at
        if end_at is not None:
            clauses.append("u.created_at <= :end_at")
            params["end_at"] = end_at
        if provider:
            clauses.append("p.slug = :provider")
            params["provider"] = provider
        if model:
            clauses.append("pm.model_slug = :model")
            params["model"] = model
        if automation_id:
            clauses.append("ar.automation_id::text = :automation_id")
            params["automation_id"] = automation_id
        if status:
            clauses.append("e.status = :execution_status")
            params["execution_status"] = status
        where_sql = " AND ".join(clauses)

        query = text(
            f"""
            SELECT
                {group_sql} AS {alias_name},
                COUNT(*)::int AS usage_rows,
                COALESCE(SUM(u.input_tokens), 0)::bigint AS input_tokens,
                COALESCE(SUM(u.output_tokens), 0)::bigint AS output_tokens,
                COALESCE(SUM(u.estimated_cost), 0) AS total_cost
            FROM django_ai_provider_usage u
            JOIN analysis_executions e ON e.id = u.execution_id
            JOIN analysis_requests ar ON ar.id = e.analysis_request_id
            JOIN django_ai_providers p ON p.id = u.provider_id
            JOIN django_ai_provider_models pm ON pm.id = u.model_id
            WHERE {where_sql}
            GROUP BY {group_sql}
            ORDER BY total_cost DESC
            """
        )
        rows = self.session.execute(query, params).mappings().all()
        return [dict(row) for row in rows]

    def list_executions_by_status(
        self,
        *,
        statuses: list[str],
        limit: int,
        start_at: datetime | None,
        end_at: datetime | None,
        provider: str | None,
        model: str | None,
        automation_id: str | None,
    ) -> list[dict[str, Any]]:
        cte, params = self._filtered_executions_cte(
            start_at=start_at,
            end_at=end_at,
            provider=provider,
            model=model,
            automation_id=automation_id,
            status=None,
        )
        params["statuses"] = statuses
        params["limit"] = limit
        query = text(
            f"""
            {cte},
            latest_queue AS (
                SELECT DISTINCT ON (q.execution_id)
                    q.execution_id,
                    q.job_status,
                    q.started_at,
                    q.finished_at,
                    q.error_message,
                    q.retry_count,
                    q.worker_name
                FROM django_ai_queue_jobs q
                ORDER BY q.execution_id, q.created_at DESC
            ),
            latest_usage AS (
                SELECT DISTINCT ON (u.execution_id)
                    u.execution_id,
                    u.input_tokens,
                    u.output_tokens,
                    u.estimated_cost,
                    p.slug AS provider,
                    pm.model_slug AS model
                FROM django_ai_provider_usage u
                JOIN django_ai_providers p ON p.id = u.provider_id
                JOIN django_ai_provider_models pm ON pm.id = u.model_id
                ORDER BY u.execution_id, u.created_at DESC
            )
            SELECT
                fe.id::text AS execution_id,
                fe.status,
                fe.analysis_request_id::text AS analysis_request_id,
                fe.automation_id::text AS automation_id,
                fe.created_at,
                lq.job_status,
                lq.started_at,
                lq.finished_at,
                lq.error_message,
                lq.retry_count,
                lq.worker_name,
                lu.provider,
                lu.model,
                lu.input_tokens,
                lu.output_tokens,
                lu.estimated_cost
            FROM filtered_executions fe
            LEFT JOIN latest_queue lq ON lq.execution_id = fe.id
            LEFT JOIN latest_usage lu ON lu.execution_id = fe.id
            WHERE fe.status = ANY(:statuses)
            ORDER BY fe.created_at DESC
            LIMIT :limit
            """
        )
        rows = self.session.execute(query, params).mappings().all()
        return [dict(row) for row in rows]

    def recent_execution_statuses(self, *, limit: int) -> list[str]:
        query = text(
            """
            SELECT e.status
            FROM analysis_executions e
            ORDER BY e.created_at DESC
            LIMIT :limit
            """
        )
        rows = self.session.execute(query, {"limit": limit}).all()
        return [str(row[0]) for row in rows]
