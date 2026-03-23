from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies.security import TokenScope, get_current_token_scope
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.schemas.external_catalog import (
    AutomationCreateRequest,
    AutomationSummaryResponse,
    AutomationListResponse,
    AutomationPromptCreateRequest,
    AutomationPromptListResponse,
    AutomationPromptResponse,
    AutomationResponse,
    AutomationUpdateRequest,
    ExternalCredentialListResponse,
    ExternalCredentialResponse,
    ExternalProviderListResponse,
    ExternalProviderModelListResponse,
    ExternalProviderModelResponse,
    ExternalProviderResponse,
    PromptUpdateRequest,
    StatusUpdateRequest,
)
from app.services.external_catalog_service import ExternalCatalogService

router = APIRouter(prefix="/api/v1/external", tags=["external-catalog"])


def _to_automation_response(item) -> AutomationResponse:  # type: ignore[no-untyped-def]
    return AutomationResponse(
        id=item.id,
        name=item.name,
        provider_id=item.provider_id,
        model_id=item.model_id,
        credential_id=item.credential_id,
        output_type=item.output_type,
        result_parser=item.result_parser,
        result_formatter=item.result_formatter,
        output_schema=item.output_schema,
        is_active=item.is_active,
    )


def _to_automation_summary_response(item) -> AutomationSummaryResponse:  # type: ignore[no-untyped-def]
    return AutomationSummaryResponse(id=item.id, name=item.name, is_active=item.is_active)


def _to_provider_response(item) -> ExternalProviderResponse:  # type: ignore[no-untyped-def]
    return ExternalProviderResponse(
        id=item.id,
        name=item.name,
        slug=item.slug,
        is_active=item.is_active,
    )


def _to_provider_model_response(item) -> ExternalProviderModelResponse:  # type: ignore[no-untyped-def]
    return ExternalProviderModelResponse(
        id=item.id,
        provider_id=item.provider_id,
        name=item.name,
        slug=item.slug,
        is_active=item.is_active,
    )


def _to_credential_response(item) -> ExternalCredentialResponse:  # type: ignore[no-untyped-def]
    return ExternalCredentialResponse(
        id=item.id,
        provider_id=item.provider_id,
        name=item.name,
        is_active=item.is_active,
    )


@router.post("/automations", response_model=AutomationResponse, status_code=status.HTTP_201_CREATED)
def create_automation(
    payload: AutomationCreateRequest,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationResponse:
    item = ExternalCatalogService(
        shared_session=shared_session,
        operational_session=operational_session,
    ).create_automation(
        token_id=token_scope.token_id,
        name=payload.name,
        provider_id=payload.provider_id,
        model_id=payload.model_id,
        credential_id=payload.credential_id,
        output_type=payload.output_type,
        result_parser=payload.result_parser,
        result_formatter=payload.result_formatter,
        output_schema=payload.output_schema,
        is_active=payload.is_active,
    )
    return _to_automation_response(item)


@router.get("/automations", response_model=AutomationListResponse)
def list_automations(
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    token_scope: TokenScope = Depends(get_current_token_scope),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationListResponse:
    items = ExternalCatalogService(shared_session=shared_session).list_automations(
        token_id=token_scope.token_id,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return AutomationListResponse(
        items=[_to_automation_summary_response(item) for item in items]
    )


@router.get("/automations/{automation_id}", response_model=AutomationResponse)
def get_automation(
    automation_id: UUID,
    token_scope: TokenScope = Depends(get_current_token_scope),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationResponse:
    item = ExternalCatalogService(shared_session=shared_session).get_automation_in_scope(
        token_id=token_scope.token_id,
        automation_id=automation_id,
    )
    return _to_automation_response(item)


@router.patch("/automations/{automation_id}", response_model=AutomationResponse)
def update_automation(
    automation_id: UUID,
    payload: AutomationUpdateRequest,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationResponse:
    item = ExternalCatalogService(
        shared_session=shared_session,
        operational_session=operational_session,
    ).update_automation(
        token_id=token_scope.token_id,
        automation_id=automation_id,
        changes=payload.model_dump(exclude_unset=True),
    )
    return _to_automation_response(item)


@router.delete("/automations/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_automation(
    automation_id: UUID,
    token_scope: TokenScope = Depends(get_current_token_scope),
    shared_session: Session = Depends(get_shared_session),
) -> Response:
    ExternalCatalogService(shared_session=shared_session).delete_automation(
        token_id=token_scope.token_id,
        automation_id=automation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/automations/{automation_id}/status", response_model=AutomationResponse)
def set_automation_status(
    automation_id: UUID,
    payload: StatusUpdateRequest,
    token_scope: TokenScope = Depends(get_current_token_scope),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationResponse:
    item = ExternalCatalogService(shared_session=shared_session).set_automation_status(
        token_id=token_scope.token_id,
        automation_id=automation_id,
        is_active=payload.is_active,
    )
    return _to_automation_response(item)


@router.get("/providers", response_model=ExternalProviderListResponse)
def list_external_providers(
    include_inactive: bool = Query(default=True),
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalProviderListResponse:
    _ = token_scope
    items = ExternalCatalogService(
        shared_session=shared_session,
        operational_session=operational_session,
    ).list_external_providers(include_inactive=include_inactive)
    return ExternalProviderListResponse(items=[_to_provider_response(item) for item in items])


@router.get("/providers/{provider_id}/models", response_model=ExternalProviderModelListResponse)
def list_external_provider_models(
    provider_id: UUID,
    include_inactive: bool = Query(default=True),
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalProviderModelListResponse:
    _ = token_scope
    items = ExternalCatalogService(
        shared_session=shared_session,
        operational_session=operational_session,
    ).list_external_provider_models(
        provider_id=provider_id,
        include_inactive=include_inactive,
    )
    return ExternalProviderModelListResponse(items=[_to_provider_model_response(item) for item in items])


@router.get("/credentials", response_model=ExternalCredentialListResponse)
def list_external_credentials(
    provider_id: UUID | None = Query(default=None),
    include_inactive: bool = Query(default=True),
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalCredentialListResponse:
    _ = token_scope
    items = ExternalCatalogService(
        shared_session=shared_session,
        operational_session=operational_session,
    ).list_external_credentials(
        provider_id=provider_id,
        include_inactive=include_inactive,
    )
    return ExternalCredentialListResponse(items=[_to_credential_response(item) for item in items])


@router.post("/prompts", response_model=AutomationPromptResponse, status_code=status.HTTP_201_CREATED)
def create_prompt(
    payload: AutomationPromptCreateRequest,
    token_scope: TokenScope = Depends(get_current_token_scope),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationPromptResponse:
    item = ExternalCatalogService(shared_session=shared_session).create_prompt(
        token_id=token_scope.token_id,
        automation_id=payload.automation_id,
        prompt_text=payload.prompt_text,
    )
    return AutomationPromptResponse(
        id=item.id,
        automation_id=item.automation_id,
        prompt_text=item.prompt_text,
        version=item.version,
        created_at=item.created_at,
        is_active=item.is_active,
    )


@router.get("/prompts", response_model=AutomationPromptListResponse)
def list_prompts(
    automation_id: UUID | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    token_scope: TokenScope = Depends(get_current_token_scope),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationPromptListResponse:
    items = ExternalCatalogService(shared_session=shared_session).list_prompts(
        token_id=token_scope.token_id,
        automation_id=automation_id,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return AutomationPromptListResponse(
        items=[
            AutomationPromptResponse(
                id=item.id,
                automation_id=item.automation_id,
                prompt_text=item.prompt_text,
                version=item.version,
                created_at=item.created_at,
                is_active=item.is_active,
            )
            for item in items
        ]
    )


@router.get("/prompts/{prompt_id}", response_model=AutomationPromptResponse)
def get_prompt(
    prompt_id: UUID,
    token_scope: TokenScope = Depends(get_current_token_scope),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationPromptResponse:
    item = ExternalCatalogService(shared_session=shared_session).get_prompt_in_scope(
        token_id=token_scope.token_id,
        prompt_id=prompt_id,
    )
    return AutomationPromptResponse(
        id=item.id,
        automation_id=item.automation_id,
        prompt_text=item.prompt_text,
        version=item.version,
        created_at=item.created_at,
        is_active=item.is_active,
    )


@router.patch("/prompts/{prompt_id}", response_model=AutomationPromptResponse)
def update_prompt(
    prompt_id: UUID,
    payload: PromptUpdateRequest,
    token_scope: TokenScope = Depends(get_current_token_scope),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationPromptResponse:
    item = ExternalCatalogService(shared_session=shared_session).update_prompt(
        token_id=token_scope.token_id,
        prompt_id=prompt_id,
        prompt_text=payload.prompt_text,
        automation_id=payload.automation_id,
    )
    return AutomationPromptResponse(
        id=item.id,
        automation_id=item.automation_id,
        prompt_text=item.prompt_text,
        version=item.version,
        created_at=item.created_at,
        is_active=item.is_active,
    )


@router.delete("/prompts/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(
    prompt_id: UUID,
    token_scope: TokenScope = Depends(get_current_token_scope),
    shared_session: Session = Depends(get_shared_session),
) -> Response:
    ExternalCatalogService(shared_session=shared_session).delete_prompt(
        token_id=token_scope.token_id,
        prompt_id=prompt_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/prompts/{prompt_id}/status", response_model=AutomationPromptResponse)
def set_prompt_status(
    prompt_id: UUID,
    payload: StatusUpdateRequest,
    token_scope: TokenScope = Depends(get_current_token_scope),
    shared_session: Session = Depends(get_shared_session),
) -> AutomationPromptResponse:
    item = ExternalCatalogService(shared_session=shared_session).set_prompt_status(
        token_id=token_scope.token_id,
        prompt_id=prompt_id,
        is_active=payload.is_active,
    )
    return AutomationPromptResponse(
        id=item.id,
        automation_id=item.automation_id,
        prompt_text=item.prompt_text,
        version=item.version,
        created_at=item.created_at,
        is_active=item.is_active,
    )
