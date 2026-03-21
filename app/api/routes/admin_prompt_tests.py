from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_admin_user
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.models.operational import DjangoAiUser
from app.schemas.admin_prompt_tests import PromptTestDirectExecutionResponse
from app.services.prompt_test_engine_service import PromptTestEngineService

router = APIRouter(tags=["admin-prompt-tests"])


@router.post(
    "/prompt-tests/executions",
    response_model=PromptTestDirectExecutionResponse,
)
def execute_prompt_test_direct(
    provider_id: UUID = Form(...),
    model_id: UUID = Form(...),
    credential_id: UUID | None = Form(None),
    prompt_override: str = Form(...),
    file: UploadFile = File(...),
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptTestDirectExecutionResponse:
    payload = PromptTestEngineService(
        operational_session=operational_session,
        shared_session=shared_session,
    ).execute(
        provider_id=str(provider_id),
        model_id=str(model_id),
        credential_id=str(credential_id) if credential_id is not None else None,
        prompt_override=prompt_override,
        upload_file=file,
    )
    return PromptTestDirectExecutionResponse(**asdict(payload))
