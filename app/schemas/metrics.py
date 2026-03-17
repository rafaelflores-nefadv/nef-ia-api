from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ExecutionMetricsResponse(BaseModel):
    totals_by_status: list[dict[str, Any]]
    total_executions: int
    running_executions: int
    failed_executions: int
    average_duration_seconds: float
    by_day: list[dict[str, Any]]
    alerts: list[str]


class UsageMetricsResponse(BaseModel):
    totals: dict[str, Any]
    by_provider: list[dict[str, Any]]
    by_model: list[dict[str, Any]]
    by_automation: list[dict[str, Any]]


class CostMetricsResponse(BaseModel):
    total_cost: float
    by_provider: list[dict[str, Any]]
    by_model: list[dict[str, Any]]
    by_automation: list[dict[str, Any]]
    alerts: list[str]


class QueueMetricsResponse(BaseModel):
    status_totals: list[dict[str, Any]]
    pending_jobs: int
    running_jobs: int
    failed_jobs: int
    average_processing_seconds: float
    total_retries: int
    oldest_queued_age_seconds: float
    alerts: list[str]


class AdminExecutionRow(BaseModel):
    execution_id: str
    status: str
    analysis_request_id: str
    automation_id: str | None
    created_at: datetime
    job_status: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    retry_count: int | None = None
    worker_name: str | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None


class AdminExecutionListResponse(BaseModel):
    items: list[AdminExecutionRow]


class ProviderUsageResponse(BaseModel):
    items: list[dict[str, Any]]
