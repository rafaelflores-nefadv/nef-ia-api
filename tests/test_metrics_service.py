from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.services.metrics_service import MetricsFilters, MetricsService


class FakeMetricsRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execution_status_totals(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("execution_status_totals", kwargs))
        return [{"status": "completed", "total": 4}, {"status": "failed", "total": 1}]

    def average_execution_duration_seconds(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("average_execution_duration_seconds", kwargs))
        return 12.5

    def execution_totals_by_day(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("execution_totals_by_day", kwargs))
        return [{"day": datetime(2026, 3, 17, tzinfo=timezone.utc), "total": 5}]

    def recent_execution_statuses(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("recent_execution_statuses", kwargs))
        return ["completed", "failed", "completed"]

    def usage_totals(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("usage_totals", kwargs))
        return {"input_tokens": 1000, "output_tokens": 400, "total_cost": Decimal("1.500000"), "usage_rows": 2}

    def usage_by_provider(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("usage_by_provider", kwargs))
        return [{"provider": "openai", "usage_rows": 2, "input_tokens": 1000, "output_tokens": 400, "total_cost": Decimal("1.5")}]

    def usage_by_model(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("usage_by_model", kwargs))
        return [{"model": "gpt-4o-mini", "usage_rows": 2, "input_tokens": 1000, "output_tokens": 400, "total_cost": Decimal("1.5")}]

    def usage_by_automation(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("usage_by_automation", kwargs))
        return [{"automation_id": "a1", "usage_rows": 2, "input_tokens": 1000, "output_tokens": 400, "total_cost": Decimal("1.5")}]

    def queue_status_totals(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("queue_status_totals", kwargs))
        return [{"job_status": "queued", "total": 2}, {"job_status": "processing", "total": 1}, {"job_status": "failed", "total": 1}]

    def queue_processing_stats(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("queue_processing_stats", kwargs))
        return {"avg_processing_seconds": 20.0, "total_retries": 3, "oldest_queued_age_seconds": 10}

    def list_executions_by_status(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("list_executions_by_status", kwargs))
        return []


class EmptyMetricsRepository(FakeMetricsRepository):
    def execution_status_totals(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("execution_status_totals", kwargs))
        return []

    def average_execution_duration_seconds(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("average_execution_duration_seconds", kwargs))
        return 0.0

    def execution_totals_by_day(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("execution_totals_by_day", kwargs))
        return []

    def recent_execution_statuses(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("recent_execution_statuses", kwargs))
        return []

    def usage_totals(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("usage_totals", kwargs))
        return {"input_tokens": 0, "output_tokens": 0, "total_cost": Decimal("0"), "usage_rows": 0}

    def usage_by_provider(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("usage_by_provider", kwargs))
        return []

    def usage_by_model(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("usage_by_model", kwargs))
        return []

    def usage_by_automation(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("usage_by_automation", kwargs))
        return []

    def queue_status_totals(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("queue_status_totals", kwargs))
        return []

    def queue_processing_stats(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("queue_processing_stats", kwargs))
        return {"avg_processing_seconds": 0, "total_retries": 0, "oldest_queued_age_seconds": 0}


def test_metrics_service_returns_aggregated_data() -> None:
    service = MetricsService(SimpleNamespace())  # type: ignore[arg-type]
    service.repository = FakeMetricsRepository()  # type: ignore[assignment]
    filters = MetricsFilters()

    payload = service.build_execution_metrics(filters)
    assert payload["total_executions"] == 5
    assert payload["failed_executions"] == 1
    assert payload["average_duration_seconds"] == 12.5

    usage_payload = service.build_usage_metrics(filters)
    assert usage_payload["totals"]["input_tokens"] == 1000
    assert usage_payload["totals"]["total_cost"] == 1.5


def test_metrics_service_handles_no_data() -> None:
    service = MetricsService(SimpleNamespace())  # type: ignore[arg-type]
    service.repository = EmptyMetricsRepository()  # type: ignore[assignment]
    filters = MetricsFilters()

    payload = service.build_execution_metrics(filters)
    assert payload["total_executions"] == 0
    assert payload["failed_executions"] == 0
    assert payload["by_day"] == []

    queue_payload = service.build_queue_metrics(filters)
    assert queue_payload["pending_jobs"] == 0
    assert queue_payload["running_jobs"] == 0
    assert queue_payload["failed_jobs"] == 0


def test_metrics_service_forwards_filters() -> None:
    service = MetricsService(SimpleNamespace())  # type: ignore[arg-type]
    fake_repo = FakeMetricsRepository()
    service.repository = fake_repo  # type: ignore[assignment]
    filters = MetricsFilters(provider="openai", model="gpt-4o-mini", status="failed")

    service.build_cost_metrics(filters)

    usage_totals_calls = [kwargs for name, kwargs in fake_repo.calls if name == "usage_totals"]
    assert usage_totals_calls
    assert usage_totals_calls[0]["provider"] == "openai"
    assert usage_totals_calls[0]["model"] == "gpt-4o-mini"
    assert usage_totals_calls[0]["status"] == "failed"


def test_admin_metrics_endpoints_are_protected() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/admin/metrics/executions")
    assert response.status_code == 401
