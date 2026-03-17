import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.repositories.operational import MetricsRepository

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MetricsFilters:
    start_at: datetime | None = None
    end_at: datetime | None = None
    provider: str | None = None
    model: str | None = None
    automation_id: str | None = None
    status: str | None = None


class MetricsService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = MetricsRepository(session)

    def build_execution_metrics(self, filters: MetricsFilters) -> dict[str, Any]:
        filter_params = asdict(filters)
        totals_by_status = self.repository.execution_status_totals(**filter_params)
        total_executions = sum(item["total"] for item in totals_by_status)
        running = sum(item["total"] for item in totals_by_status if item["status"] in {"queued", "processing", "generating_output"})
        failed = sum(item["total"] for item in totals_by_status if item["status"] == "failed")
        average_duration = self.repository.average_execution_duration_seconds(**filter_params)
        by_day = self.repository.execution_totals_by_day(**filter_params)

        alerts = self._build_alerts_for_execution_and_queue(failed_count=failed, total_executions=total_executions)
        return {
            "totals_by_status": totals_by_status,
            "total_executions": total_executions,
            "running_executions": running,
            "failed_executions": failed,
            "average_duration_seconds": round(average_duration, 4),
            "by_day": by_day,
            "alerts": alerts,
        }

    def build_usage_metrics(self, filters: MetricsFilters) -> dict[str, Any]:
        filter_params = asdict(filters)
        totals = self.repository.usage_totals(**filter_params)
        by_provider = self.repository.usage_by_provider(**filter_params)
        by_model = self.repository.usage_by_model(**filter_params)
        by_automation = self.repository.usage_by_automation(**filter_params)

        return {
            "totals": self._normalize_cost_values(totals),
            "by_provider": self._normalize_cost_values(by_provider),
            "by_model": self._normalize_cost_values(by_model),
            "by_automation": self._normalize_cost_values(by_automation),
        }

    def build_cost_metrics(self, filters: MetricsFilters) -> dict[str, Any]:
        filter_params = asdict(filters)
        usage_totals = self.repository.usage_totals(**filter_params)
        total_cost = self._to_float(usage_totals.get("total_cost"))
        alerts: list[str] = []
        if total_cost > settings.alert_cost_threshold:
            alert = f"Cost threshold exceeded: {total_cost:.6f} > {settings.alert_cost_threshold:.6f}"
            alerts.append(alert)
            logger.error("Cost threshold exceeded.", extra={"event": "cost_alert", "estimated_cost": total_cost})

        by_provider = self.repository.usage_by_provider(**filter_params)
        by_model = self.repository.usage_by_model(**filter_params)
        by_automation = self.repository.usage_by_automation(**filter_params)
        return {
            "total_cost": total_cost,
            "by_provider": self._normalize_cost_values(by_provider),
            "by_model": self._normalize_cost_values(by_model),
            "by_automation": self._normalize_cost_values(by_automation),
            "alerts": alerts,
        }

    def build_queue_metrics(self, filters: MetricsFilters) -> dict[str, Any]:
        filter_params = asdict(filters)
        status_totals = self.repository.queue_status_totals(**filter_params)
        stats = self.repository.queue_processing_stats(**filter_params)

        pending = sum(item["total"] for item in status_totals if item["job_status"] in {"pending", "queued"})
        running = sum(item["total"] for item in status_totals if item["job_status"] in {"processing", "generating_output"})
        failed = sum(item["total"] for item in status_totals if item["job_status"] == "failed")
        oldest_queued_age_seconds = float(stats.get("oldest_queued_age_seconds") or 0)
        alerts: list[str] = []
        if oldest_queued_age_seconds > settings.alert_queue_stuck_minutes * 60:
            alert = (
                "Queue appears stuck: "
                f"{oldest_queued_age_seconds:.0f}s waiting (limit {settings.alert_queue_stuck_minutes * 60}s)."
            )
            alerts.append(alert)
            logger.error("Queue stuck alert triggered.", extra={"event": "queue_stuck_alert"})

        return {
            "status_totals": status_totals,
            "pending_jobs": pending,
            "running_jobs": running,
            "failed_jobs": failed,
            "average_processing_seconds": round(float(stats.get("avg_processing_seconds") or 0), 4),
            "total_retries": int(stats.get("total_retries") or 0),
            "oldest_queued_age_seconds": oldest_queued_age_seconds,
            "alerts": alerts,
        }

    def list_failed_executions(self, *, filters: MetricsFilters, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.repository.list_executions_by_status(
            statuses=["failed"],
            limit=limit,
            start_at=filters.start_at,
            end_at=filters.end_at,
            provider=filters.provider,
            model=filters.model,
            automation_id=filters.automation_id,
        )
        return self._normalize_cost_values(rows)

    def list_running_executions(self, *, filters: MetricsFilters, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.repository.list_executions_by_status(
            statuses=["queued", "processing", "generating_output"],
            limit=limit,
            start_at=filters.start_at,
            end_at=filters.end_at,
            provider=filters.provider,
            model=filters.model,
            automation_id=filters.automation_id,
        )
        return self._normalize_cost_values(rows)

    def providers_usage(self, filters: MetricsFilters) -> list[dict[str, Any]]:
        filter_params = asdict(filters)
        by_provider = self.repository.usage_by_provider(**filter_params)
        return self._normalize_cost_values(by_provider)

    def _build_alerts_for_execution_and_queue(self, *, failed_count: int, total_executions: int) -> list[str]:
        alerts: list[str] = []
        recent_statuses = self.repository.recent_execution_statuses(limit=settings.alert_failure_streak_threshold)
        if len(recent_statuses) >= settings.alert_failure_streak_threshold and all(
            status == "failed" for status in recent_statuses[: settings.alert_failure_streak_threshold]
        ):
            alert = f"Failure streak alert: {settings.alert_failure_streak_threshold} failed executions in sequence."
            alerts.append(alert)
            logger.error("Failure streak alert triggered.", extra={"event": "failure_streak_alert"})

        if failed_count > 0 and total_executions > 0:
            error_rate = failed_count / total_executions
            if error_rate >= 0.5:
                alert = f"High failure ratio detected: {error_rate:.2%}"
                alerts.append(alert)
                logger.error("High failure ratio detected.", extra={"event": "failure_ratio_alert"})
        return alerts

    @classmethod
    def _normalize_cost_values(cls, data: Any) -> Any:
        if isinstance(data, list):
            return [cls._normalize_cost_values(item) for item in data]
        if isinstance(data, dict):
            normalized: dict[str, Any] = {}
            for key, value in data.items():
                if key.endswith("_cost"):
                    normalized[key] = cls._to_float(value)
                else:
                    normalized[key] = cls._normalize_cost_values(value)
            return normalized
        return data

    @staticmethod
    def _to_float(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, Decimal):
            return float(value)
        return float(value)
