from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_admin_user
from app.db.session import SessionLocal, get_operational_session
from app.models.operational import DjangoAiUser
from app.schemas.admin_prompt_tests import PromptTestCreateResponse, PromptTestStatusResponse
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


@router.get("/prompt-tests/{prompt_test_id}", response_model=PromptTestStatusResponse)
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
