from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_admin_user
from app.db.session import get_operational_session
from app.models.operational import DjangoAiUser
from app.schemas.metrics import (
    AdminExecutionListResponse,
    AdminExecutionRow,
    CostMetricsResponse,
    ExecutionMetricsResponse,
    ProviderUsageResponse,
    QueueMetricsResponse,
    UsageMetricsResponse,
)
from app.services.metrics_service import MetricsFilters, MetricsService

router = APIRouter(tags=["admin-metrics"])


def _build_filters(
    *,
    start_at: datetime | None,
    end_at: datetime | None,
    provider: str | None,
    model: str | None,
    automation_id: UUID | None,
    status: str | None,
) -> MetricsFilters:
    return MetricsFilters(
        start_at=start_at,
        end_at=end_at,
        provider=provider,
        model=model,
        automation_id=str(automation_id) if automation_id else None,
        status=status,
    )


@router.get("/metrics/executions", response_model=ExecutionMetricsResponse)
def get_execution_metrics(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    automation_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ExecutionMetricsResponse:
    filters = _build_filters(
        start_at=start_at,
        end_at=end_at,
        provider=provider,
        model=model,
        automation_id=automation_id,
        status=status,
    )
    payload = MetricsService(session).build_execution_metrics(filters)
    return ExecutionMetricsResponse(**payload)


@router.get("/metrics/usage", response_model=UsageMetricsResponse)
def get_usage_metrics(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    automation_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> UsageMetricsResponse:
    filters = _build_filters(
        start_at=start_at,
        end_at=end_at,
        provider=provider,
        model=model,
        automation_id=automation_id,
        status=status,
    )
    payload = MetricsService(session).build_usage_metrics(filters)
    return UsageMetricsResponse(**payload)


@router.get("/metrics/costs", response_model=CostMetricsResponse)
def get_cost_metrics(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    automation_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> CostMetricsResponse:
    filters = _build_filters(
        start_at=start_at,
        end_at=end_at,
        provider=provider,
        model=model,
        automation_id=automation_id,
        status=status,
    )
    payload = MetricsService(session).build_cost_metrics(filters)
    return CostMetricsResponse(**payload)


@router.get("/metrics/queue", response_model=QueueMetricsResponse)
def get_queue_metrics(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    automation_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> QueueMetricsResponse:
    filters = _build_filters(
        start_at=start_at,
        end_at=end_at,
        provider=provider,
        model=model,
        automation_id=automation_id,
        status=status,
    )
    payload = MetricsService(session).build_queue_metrics(filters)
    return QueueMetricsResponse(**payload)


@router.get("/executions/failed", response_model=AdminExecutionListResponse)
def list_failed_executions(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    automation_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> AdminExecutionListResponse:
    filters = _build_filters(
        start_at=start_at,
        end_at=end_at,
        provider=provider,
        model=model,
        automation_id=automation_id,
        status=None,
    )
    items = MetricsService(session).list_failed_executions(filters=filters, limit=limit)
    return AdminExecutionListResponse(items=[AdminExecutionRow(**item) for item in items])


@router.get("/executions/running", response_model=AdminExecutionListResponse)
def list_running_executions(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    automation_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> AdminExecutionListResponse:
    filters = _build_filters(
        start_at=start_at,
        end_at=end_at,
        provider=provider,
        model=model,
        automation_id=automation_id,
        status=None,
    )
    items = MetricsService(session).list_running_executions(filters=filters, limit=limit)
    return AdminExecutionListResponse(items=[AdminExecutionRow(**item) for item in items])


@router.get("/providers/usage", response_model=ProviderUsageResponse)
def providers_usage(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    automation_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderUsageResponse:
    filters = _build_filters(
        start_at=start_at,
        end_at=end_at,
        provider=provider,
        model=model,
        automation_id=automation_id,
        status=status,
    )
    items = MetricsService(session).providers_usage(filters)
    return ProviderUsageResponse(items=items)
