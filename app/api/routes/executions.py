from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_token
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.models.operational import DjangoAiApiToken
from app.schemas.execution import (
    ExecutionCreateRequest,
    ExecutionCreateResponse,
    ExecutionListResponse,
    ExecutionStatusResponse,
)
from app.services.execution_service import ExecutionService

router = APIRouter(prefix="/api/v1", tags=["executions"])


@router.post("/executions", response_model=ExecutionCreateResponse, status_code=status.HTTP_201_CREATED)
def create_execution(
    payload: ExecutionCreateRequest,
    request: Request,
    api_token: DjangoAiApiToken = Depends(get_current_token),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExecutionCreateResponse:
    token_permissions = getattr(request.state, "token_permissions", [])
    ip_address = request.client.host if request.client else None

    service = ExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    result = service.create_execution(
        analysis_request_id=payload.analysis_request_id,
        request_file_id=payload.request_file_id,
        api_token=api_token,
        token_permissions=token_permissions,
        ip_address=ip_address,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    request.state.execution_id = result.execution_id
    return ExecutionCreateResponse(
        execution_id=result.execution_id,
        queue_job_id=result.queue_job_id,
        status=result.status,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionStatusResponse)
def get_execution_status(
    execution_id: UUID,
    request: Request,
    _: DjangoAiApiToken = Depends(get_current_token),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExecutionStatusResponse:
    token_permissions = getattr(request.state, "token_permissions", [])
    service = ExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    result = service.get_execution_status(
        execution_id=execution_id,
        token_permissions=token_permissions,
    )
    return ExecutionStatusResponse(
        execution_id=result.execution_id,
        status=result.status,
        progress=result.progress,
        started_at=result.started_at,
        finished_at=result.finished_at,
        error_message=result.error_message,
        created_at=result.created_at,
    )


@router.get("/analysis-requests/{analysis_request_id}/executions", response_model=ExecutionListResponse)
def list_executions_by_analysis_request(
    analysis_request_id: UUID,
    request: Request,
    _: DjangoAiApiToken = Depends(get_current_token),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExecutionListResponse:
    token_permissions = getattr(request.state, "token_permissions", [])
    service = ExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    items = service.list_executions_for_analysis_request(
        analysis_request_id=analysis_request_id,
        token_permissions=token_permissions,
    )
    return ExecutionListResponse(
        items=[
            ExecutionStatusResponse(
                execution_id=item.execution_id,
                status=item.status,
                progress=item.progress,
                started_at=item.started_at,
                finished_at=item.finished_at,
                error_message=item.error_message,
                created_at=item.created_at,
            )
            for item in items
        ]
    )
