from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_admin_user
from app.db.session import SessionLocal, get_operational_session
from app.db.shared_session import get_shared_session
from app.models.operational import DjangoAiUser
from app.schemas.admin_prompt_tests import (
    PromptTestAutomationListResponse,
    PromptTestAutomationResponse,
    PromptTestAutomationUpdateRequest,
    PromptTestCreateResponse,
    PromptTestRuntimeConfigureRequest,
    PromptTestTechnicalRuntimeResponse,
    PromptTestStatusResponse,
)
from app.services.admin_automation_execution_service import AdminAutomationExecutionService
from app.services.prompt_test_service import PromptTestService

router = APIRouter(tags=["admin-prompt-tests"])


def _run_prompt_test_in_background(*, prompt_test_id: UUID, file_content: bytes) -> None:
    with SessionLocal() as session:
        PromptTestService(session).process_prompt_test(
            prompt_test_id=prompt_test_id,
            file_content=file_content,
        )


@router.post(
    "/prompt-tests",
    response_model=PromptTestCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_prompt_test(
    background_tasks: BackgroundTasks,
    prompt_text: str = Form(...),
    provider_slug: str = Form(...),
    model_slug: str = Form(...),
    file: UploadFile = File(...),
    prompt_title: str = Form(""),
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> PromptTestCreateResponse:
    file_content = file.file.read()
    service = PromptTestService(session)
    record = service.create_prompt_test(
        prompt_title=prompt_title,
        prompt_text=prompt_text,
        provider_slug=provider_slug,
        model_slug=model_slug,
        file_name=str(file.filename or "").strip(),
        file_size=len(file_content),
    )

    background_tasks.add_task(
        _run_prompt_test_in_background,
        prompt_test_id=record.id,
        file_content=file_content,
    )

    return PromptTestCreateResponse(
        id=record.id,
        status=record.status,
        prompt_title=record.prompt_title,
        provider_slug=record.provider_slug,
        model_slug=record.model_slug,
        file_name=record.file_name,
        created_at=record.created_at,
    )


@router.get("/prompt-tests/runtime", response_model=PromptTestTechnicalRuntimeResponse)
def get_prompt_test_runtime(
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptTestTechnicalRuntimeResponse:
    service = AdminAutomationExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    payload = service.get_prompt_test_runtime()
    return PromptTestTechnicalRuntimeResponse(**payload)


@router.get(
    "/prompt-tests/automations",
    response_model=PromptTestAutomationListResponse,
)
def list_prompt_test_automations(
    active_only: bool = True,
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptTestAutomationListResponse:
    service = AdminAutomationExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    items = service.list_test_automations(active_only=active_only)
    return PromptTestAutomationListResponse(
        total=len(items),
        items=[PromptTestAutomationResponse(**item) for item in items],
    )


@router.get(
    "/prompt-tests/automations/{automation_id}",
    response_model=PromptTestAutomationResponse,
)
def get_prompt_test_automation(
    automation_id: UUID,
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptTestAutomationResponse:
    service = AdminAutomationExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    return PromptTestAutomationResponse(**service.get_test_automation(automation_id=automation_id))


def _create_prompt_test_automation_payload(
    payload: PromptTestRuntimeConfigureRequest,
    operational_session: Session,
    shared_session: Session,
) -> PromptTestAutomationResponse:
    service = AdminAutomationExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    result = service.create_test_automation(
        name=payload.name,
        provider_id=payload.provider_id,
        model_id=payload.model_id,
    )
    return PromptTestAutomationResponse(**result)


@router.post(
    "/prompt-tests/automations",
    response_model=PromptTestAutomationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_prompt_test_automation(
    payload: PromptTestRuntimeConfigureRequest,
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptTestAutomationResponse:
    return _create_prompt_test_automation_payload(
        payload=payload,
        operational_session=operational_session,
        shared_session=shared_session,
    )


@router.put(
    "/prompt-tests/automations/{automation_id}",
    response_model=PromptTestAutomationResponse,
)
def update_prompt_test_automation(
    automation_id: UUID,
    payload: PromptTestAutomationUpdateRequest,
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptTestAutomationResponse:
    service = AdminAutomationExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    result = service.update_test_automation(
        automation_id=automation_id,
        name=payload.name,
        provider_id=payload.provider_id,
        model_id=payload.model_id,
        is_active=payload.is_active,
    )
    return PromptTestAutomationResponse(**result)


@router.delete(
    "/prompt-tests/automations/{automation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_prompt_test_automation(
    automation_id: UUID,
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> None:
    service = AdminAutomationExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    service.delete_test_automation(automation_id=automation_id)


@router.post(
    "/prompt-tests/runtime",
    response_model=PromptTestAutomationResponse,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
def configure_prompt_test_runtime(
    payload: PromptTestRuntimeConfigureRequest,
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptTestAutomationResponse:
    return _create_prompt_test_automation_payload(
        payload=payload,
        operational_session=operational_session,
        shared_session=shared_session,
    )


@router.get("/prompt-tests/{prompt_test_id:uuid}", response_model=PromptTestStatusResponse)
def get_prompt_test_status(
    prompt_test_id: UUID,
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> PromptTestStatusResponse:
    record = PromptTestService(session).get_prompt_test(prompt_test_id=prompt_test_id)
    return PromptTestStatusResponse(
        id=record.id,
        status=record.status,
        prompt_title=record.prompt_title,
        provider_slug=record.provider_slug,
        model_slug=record.model_slug,
        file_name=record.file_name,
        file_size=record.file_size,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        error_message=record.error_message,
        output_text=record.output_text,
    )
