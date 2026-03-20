from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_admin_user
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.models.operational import DjangoAiUser
from app.schemas.admin_execution_profiles import (
    AutomationExecutionSettingsListResponse,
    AutomationExecutionSettingResponse,
    AutomationExecutionSettingsUpsertRequest,
)
from app.services.automation_execution_settings_service import AutomationExecutionSettingsService

router = APIRouter(tags=["admin-execution-profiles"])


@router.get(
    "/automation-execution-settings",
    response_model=AutomationExecutionSettingsListResponse,
)
def list_automation_execution_settings(
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationExecutionSettingsListResponse:
    service = AutomationExecutionSettingsService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    items = service.list_automation_settings()
    return AutomationExecutionSettingsListResponse(
        generated_at=datetime.now(timezone.utc),
        total=len(items),
        items=[AutomationExecutionSettingResponse(**item) for item in items],
    )


@router.get(
    "/automation-execution-settings/{automation_id}",
    response_model=AutomationExecutionSettingResponse,
)
def get_automation_execution_setting(
    automation_id: UUID,
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationExecutionSettingResponse:
    service = AutomationExecutionSettingsService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    payload = service.get_automation_setting(automation_id=automation_id)
    return AutomationExecutionSettingResponse(**payload)


@router.put(
    "/automation-execution-settings/{automation_id}",
    response_model=AutomationExecutionSettingResponse,
)
def upsert_automation_execution_setting(
    automation_id: UUID,
    payload: AutomationExecutionSettingsUpsertRequest,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationExecutionSettingResponse:
    service = AutomationExecutionSettingsService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    result = service.upsert_automation_setting(
        automation_id=automation_id,
        execution_profile=payload.execution_profile,
        is_active=payload.is_active,
        max_execution_rows=payload.max_execution_rows,
        max_provider_calls=payload.max_provider_calls,
        max_text_chunks=payload.max_text_chunks,
        max_tabular_row_characters=payload.max_tabular_row_characters,
        max_execution_seconds=payload.max_execution_seconds,
        max_context_characters=payload.max_context_characters,
        max_context_file_characters=payload.max_context_file_characters,
        max_prompt_characters=payload.max_prompt_characters,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return AutomationExecutionSettingResponse(**result)
