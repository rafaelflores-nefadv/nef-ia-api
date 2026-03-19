from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_admin_user
from app.db.session import get_operational_session
from app.models.operational import DjangoAiProvider, DjangoAiProviderCredential, DjangoAiProviderModel, DjangoAiUser
from app.schemas.admin_catalog import (
    AvailableProviderModelResponse,
    CatalogStatusResponse,
    ProviderConnectivityTestResponse,
    ProviderCreateRequest,
    ProviderCredentialCreateRequest,
    ProviderCredentialResponse,
    ProviderCredentialUpdateRequest,
    ProviderModelCreateRequest,
    ProviderModelResponse,
    ProviderModelUpdateRequest,
    ProviderResponse,
    ProviderUpdateRequest,
)
from app.services.provider_admin_service import ProviderAdminService
from app.services.provider_connectivity_service import ProviderConnectivityService
from app.services.provider_model_discovery_service import ProviderModelDiscoveryService

router = APIRouter(tags=["admin-catalog"])


def _provider_to_response(item: DjangoAiProvider) -> ProviderResponse:
    return ProviderResponse(
        id=item.id,
        name=item.name,
        slug=item.slug,
        description=item.description,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _model_to_response(item: DjangoAiProviderModel) -> ProviderModelResponse:
    return ProviderModelResponse(
        id=item.id,
        provider_id=item.provider_id,
        model_name=item.model_name,
        model_slug=item.model_slug,
        context_limit=item.context_limit,
        cost_input_per_1k_tokens=item.cost_input_per_1k_tokens,
        cost_output_per_1k_tokens=item.cost_output_per_1k_tokens,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _credential_to_response(item: DjangoAiProviderCredential) -> ProviderCredentialResponse:
    return ProviderCredentialResponse(
        id=item.id,
        provider_id=item.provider_id,
        credential_name=item.credential_name,
        config_json=item.config_json or {},
        is_active=item.is_active,
        secret_masked=ProviderAdminService.mask_credential_secret(item.encrypted_api_key),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/providers", response_model=list[ProviderResponse])
def list_providers(
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> list[ProviderResponse]:
    service = ProviderAdminService(session)
    return [_provider_to_response(item) for item in service.list_providers()]


@router.post("/providers", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
def create_provider(
    payload: ProviderCreateRequest,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderResponse:
    service = ProviderAdminService(session)
    provider = service.create_provider(
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        is_active=payload.is_active,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return _provider_to_response(provider)


@router.patch("/providers/{provider_id}", response_model=ProviderResponse)
def update_provider(
    provider_id: UUID,
    payload: ProviderUpdateRequest,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderResponse:
    provider = ProviderAdminService(session).update_provider(
        provider_id=provider_id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        is_active=payload.is_active,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return _provider_to_response(provider)


@router.patch("/providers/{provider_id}/activate", response_model=ProviderResponse)
def activate_provider(
    provider_id: UUID,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderResponse:
    provider = ProviderAdminService(session).activate_provider(
        provider_id=provider_id,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return _provider_to_response(provider)


@router.patch("/providers/{provider_id}/deactivate", response_model=ProviderResponse)
def deactivate_provider(
    provider_id: UUID,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderResponse:
    provider = ProviderAdminService(session).deactivate_provider(
        provider_id=provider_id,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return _provider_to_response(provider)


@router.get("/providers/{provider_id}/models", response_model=list[ProviderModelResponse])
def list_provider_models(
    provider_id: UUID,
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> list[ProviderModelResponse]:
    service = ProviderAdminService(session)
    return [_model_to_response(item) for item in service.list_models(provider_id=provider_id)]


@router.get("/providers/{provider_id}/available-models", response_model=list[AvailableProviderModelResponse])
def list_provider_available_models(
    provider_id: UUID,
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> list[AvailableProviderModelResponse]:
    payload = ProviderModelDiscoveryService(session).list_available_models(provider_id=provider_id)
    return [AvailableProviderModelResponse(**item) for item in payload]


@router.post(
    "/providers/{provider_id}/connectivity-test",
    response_model=ProviderConnectivityTestResponse,
)
def test_provider_connectivity(
    provider_id: UUID,
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderConnectivityTestResponse:
    payload = ProviderConnectivityService(session).test_provider_connectivity(provider_id=provider_id)
    return ProviderConnectivityTestResponse(**payload)


@router.post("/providers/{provider_id}/models", response_model=ProviderModelResponse, status_code=status.HTTP_201_CREATED)
def create_provider_model(
    provider_id: UUID,
    payload: ProviderModelCreateRequest,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderModelResponse:
    model = ProviderAdminService(session).create_model(
        provider_id=provider_id,
        model_name=payload.model_name,
        model_slug=payload.model_slug,
        context_limit=payload.context_limit,
        cost_input_per_1k_tokens=payload.cost_input_per_1k_tokens,
        cost_output_per_1k_tokens=payload.cost_output_per_1k_tokens,
        is_active=payload.is_active,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return _model_to_response(model)


@router.patch("/models/{model_id}", response_model=ProviderModelResponse)
def update_provider_model(
    model_id: UUID,
    payload: ProviderModelUpdateRequest,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderModelResponse:
    model = ProviderAdminService(session).update_model(
        model_id=model_id,
        model_name=payload.model_name,
        model_slug=payload.model_slug,
        context_limit=payload.context_limit,
        cost_input_per_1k_tokens=payload.cost_input_per_1k_tokens,
        cost_output_per_1k_tokens=payload.cost_output_per_1k_tokens,
        is_active=payload.is_active,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return _model_to_response(model)


@router.patch("/models/{model_id}/activate", response_model=ProviderModelResponse)
def activate_provider_model(
    model_id: UUID,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderModelResponse:
    model = ProviderAdminService(session).activate_model(
        model_id=model_id,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return _model_to_response(model)


@router.patch("/models/{model_id}/deactivate", response_model=ProviderModelResponse)
def deactivate_provider_model(
    model_id: UUID,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderModelResponse:
    model = ProviderAdminService(session).deactivate_model(
        model_id=model_id,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return _model_to_response(model)


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider_model(
    model_id: UUID,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> Response:
    ProviderAdminService(session).delete_model(
        model_id=model_id,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/providers/{provider_id}/credentials", response_model=list[ProviderCredentialResponse])
def list_provider_credentials(
    provider_id: UUID,
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> list[ProviderCredentialResponse]:
    service = ProviderAdminService(session)
    return [_credential_to_response(item) for item in service.list_credentials(provider_id=provider_id)]


@router.post(
    "/providers/{provider_id}/credentials",
    response_model=ProviderCredentialResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_provider_credential(
    provider_id: UUID,
    payload: ProviderCredentialCreateRequest,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderCredentialResponse:
    credential = ProviderAdminService(session).create_credential(
        provider_id=provider_id,
        credential_name=payload.credential_name,
        api_key=payload.api_key,
        config_json=payload.config_json,
        is_active=payload.is_active,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return _credential_to_response(credential)


@router.patch("/credentials/{credential_id}", response_model=ProviderCredentialResponse)
def update_provider_credential(
    credential_id: UUID,
    payload: ProviderCredentialUpdateRequest,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderCredentialResponse:
    credential = ProviderAdminService(session).update_credential(
        credential_id=credential_id,
        credential_name=payload.credential_name,
        api_key=payload.api_key,
        config_json=payload.config_json,
        is_active=payload.is_active,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return _credential_to_response(credential)


@router.patch("/credentials/{credential_id}/activate", response_model=ProviderCredentialResponse)
def activate_provider_credential(
    credential_id: UUID,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderCredentialResponse:
    credential = ProviderAdminService(session).activate_credential(
        credential_id=credential_id,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return _credential_to_response(credential)


@router.patch("/credentials/{credential_id}/deactivate", response_model=ProviderCredentialResponse)
def deactivate_provider_credential(
    credential_id: UUID,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ProviderCredentialResponse:
    credential = ProviderAdminService(session).deactivate_credential(
        credential_id=credential_id,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return _credential_to_response(credential)


@router.get("/catalog/status", response_model=CatalogStatusResponse)
def catalog_status(
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> CatalogStatusResponse:
    payload = ProviderAdminService(session).build_catalog_status()
    return CatalogStatusResponse(**payload)
