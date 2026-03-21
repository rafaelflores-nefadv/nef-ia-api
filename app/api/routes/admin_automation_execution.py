from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_admin_user
from app.core.exceptions import AppException
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.models.operational import DjangoAiUser
from app.schemas.admin_automation_execution import (
    AdminExecutionStatusResponse,
    AutomationExecutionCreateResponse,
    AutomationRuntimeDetailResponse,
    AutomationRuntimeItemResponse,
    AutomationRuntimeListResponse,
    TestAutomationCreateRequest,
    TestAutomationCreateResponse,
)
from app.services.admin_automation_execution_service import AdminAutomationExecutionService

router = APIRouter(tags=["admin-automation-execution"])


@router.post(
    "/automations",
    response_model=TestAutomationCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_test_automation(
    payload: TestAutomationCreateRequest,
    _: DjangoAiUser = Depends(get_current_admin_user),
) -> TestAutomationCreateResponse:
    raise AppException(
        "Endpoint deprecated for prompt-test automation creation. Use /api/v1/admin/prompt-tests/automations.",
        status_code=status.HTTP_410_GONE,
        code="test_prompt_runtime_endpoint_deprecated",
        details={
            "replacement_endpoint": "/api/v1/admin/prompt-tests/automations",
            "received_name": payload.name,
            "received_provider_id": str(payload.provider_id),
            "received_model_id": str(payload.model_id),
        },
    )


@router.get(
    "/automations/runtime",
    response_model=AutomationRuntimeListResponse,
)
def list_automation_runtimes(
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationRuntimeListResponse:
    service = AdminAutomationExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    items = service.list_automation_runtimes()
    return AutomationRuntimeListResponse(
        generated_at=datetime.now(timezone.utc),
        total=len(items),
        items=[AutomationRuntimeItemResponse(**item) for item in items],
    )


@router.get(
    "/automations/runtime/{automation_id}",
    response_model=AutomationRuntimeDetailResponse,
)
def get_automation_runtime(
    automation_id: UUID,
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationRuntimeDetailResponse:
    service = AdminAutomationExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    payload = service.get_automation_runtime(automation_id=automation_id)
    return AutomationRuntimeDetailResponse(**payload)


@router.post(
    "/automations/{automation_id}/executions",
    response_model=AutomationExecutionCreateResponse,
)
def create_automation_execution(
    automation_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    prompt_override: str | None = Form(default=None),
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationExecutionCreateResponse:
    service = AdminAutomationExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    result = service.start_execution_for_automation(
        automation_id=automation_id,
        upload_file=file,
        prompt_override=prompt_override,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    return AutomationExecutionCreateResponse(
        automation_id=result.automation_id,
        analysis_request_id=result.analysis_request_id,
        request_file_id=result.request_file_id,
        execution_id=result.execution_id,
        queue_job_id=result.queue_job_id,
        status=result.status,
        prompt_version=result.prompt_version,
        prompt_override_applied=result.prompt_override_applied,
    )


@router.get(
    "/executions/{execution_id}/status",
    response_model=AdminExecutionStatusResponse,
)
def get_execution_status(
    execution_id: UUID,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> AdminExecutionStatusResponse:
    service = AdminAutomationExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    payload = service.get_execution_status_for_admin(
        execution_id=execution_id,
        actor_user_id=current_user.id,
    )
    return AdminExecutionStatusResponse(**payload)


@router.get("/execution-files/{file_id}/download")
def download_execution_file(
    file_id: UUID,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> FileResponse:
    service = AdminAutomationExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    downloadable = service.get_execution_file_for_admin_download(
        file_id=file_id,
        actor_user_id=current_user.id,
    )
    headers = {}
    if downloadable.checksum:
        headers["X-File-Checksum"] = downloadable.checksum
    return FileResponse(
        downloadable.absolute_path,
        media_type=downloadable.mime_type or "application/octet-stream",
        filename=downloadable.file_name,
        headers=headers,
    )
