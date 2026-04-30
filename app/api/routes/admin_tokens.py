from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_admin_user
from app.db.session import get_operational_session
from app.models.operational import DjangoAiUser
from app.schemas.admin_tokens import (
    ApiTokenCreateRequest,
    ApiTokenCreateResponse,
    ApiTokenListItem,
    ApiTokenRevokedResponse,
    IntegrationTokenCreateRequest,
    IntegrationTokenCreateResponse,
    IntegrationTokenDeactivatedResponse,
    IntegrationTokenListItem,
    IntegrationTokenTestResponse,
)
from app.services.integration_token_service import IntegrationTokenService
from app.services.token_service import ApiTokenService

router = APIRouter(tags=["admin-tokens"])


@router.post("/tokens", response_model=ApiTokenCreateResponse, status_code=status.HTTP_201_CREATED)
def create_api_token(
    payload: ApiTokenCreateRequest,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ApiTokenCreateResponse:
    ip_address = request.client.host if request.client else None
    token_model, raw_token = ApiTokenService(session).create_token(
        name=payload.name,
        created_by_user_id=current_user.id,
        expires_at=payload.expires_at,
        permissions=[permission.model_dump() for permission in payload.permissions],
        ip_address=ip_address,
    )
    return ApiTokenCreateResponse(
        id=token_model.id,
        name=token_model.name,
        token=raw_token,
        is_active=token_model.is_active,
        expires_at=token_model.expires_at,
        created_at=token_model.created_at,
    )


@router.get("/tokens", response_model=list[ApiTokenListItem])
def list_api_tokens(
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> list[ApiTokenListItem]:
    tokens = ApiTokenService(session).list_tokens()
    return [
        ApiTokenListItem(
            id=token.id,
            name=token.name,
            is_active=token.is_active,
            expires_at=token.expires_at,
            created_by_user_id=token.created_by_user_id,
            created_at=token.created_at,
            updated_at=token.updated_at,
        )
        for token in tokens
    ]


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_token(
    token_id: UUID,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> Response:
    ip_address = request.client.host if request.client else None
    ApiTokenService(session).delete_token(
        token_id=token_id,
        actor_user_id=current_user.id,
        ip_address=ip_address,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/tokens/{token_id}/revoke", response_model=ApiTokenRevokedResponse)
def revoke_api_token(
    token_id: UUID,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> ApiTokenRevokedResponse:
    ip_address = request.client.host if request.client else None
    token = ApiTokenService(session).revoke_token(
        token_id=token_id,
        actor_user_id=current_user.id,
        ip_address=ip_address,
    )
    return ApiTokenRevokedResponse(id=token.id, is_active=token.is_active)


@router.post(
    "/integration-tokens",
    response_model=IntegrationTokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_integration_token(
    payload: IntegrationTokenCreateRequest,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> IntegrationTokenCreateResponse:
    ip_address = request.client.host if request.client else None
    token_model, raw_token = IntegrationTokenService(session).create_token(
        name=payload.name,
        created_by_user_id=current_user.id,
        ip_address=ip_address,
    )
    ApiTokenService(session).create_token(
        name=payload.name,
        created_by_user_id=current_user.id,
        expires_at=None,
        permissions=[],
        ip_address=ip_address,
    )
    return IntegrationTokenCreateResponse(
        id=token_model.id,
        name=token_model.name,
        token=raw_token,
        is_active=token_model.is_active,
        created_by_user_id=token_model.created_by_user_id,
        created_at=token_model.created_at,
    )


@router.get("/integration-tokens", response_model=list[IntegrationTokenListItem])
def list_integration_tokens(
    _: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> list[IntegrationTokenListItem]:
    service = IntegrationTokenService(session)
    tokens = service.list_tokens()
    return [
        IntegrationTokenListItem(
            id=token.id,
            name=token.name,
            token_hash_masked=service.mask_token_hash(token.token_hash),
            is_active=token.is_active,
            last_used_at=token.last_used_at,
            created_by_user_id=token.created_by_user_id,
            created_at=token.created_at,
            updated_at=token.updated_at,
        )
        for token in tokens
    ]


@router.patch(
    "/integration-tokens/{token_id}/deactivate",
    response_model=IntegrationTokenDeactivatedResponse,
)
def deactivate_integration_token(
    token_id: UUID,
    request: Request,
    current_user: DjangoAiUser = Depends(get_current_admin_user),
    session: Session = Depends(get_operational_session),
) -> IntegrationTokenDeactivatedResponse:
    ip_address = request.client.host if request.client else None
    token = IntegrationTokenService(session).deactivate_token(
        token_id=token_id,
        actor_user_id=current_user.id,
        ip_address=ip_address,
    )
    return IntegrationTokenDeactivatedResponse(id=token.id, is_active=token.is_active)


@router.get("/integration-tokens/test", response_model=IntegrationTokenTestResponse)
def test_integration_token(
    request: Request,
    _: DjangoAiUser = Depends(get_current_admin_user),
) -> IntegrationTokenTestResponse:
    auth_mode = str(getattr(request.state, "admin_auth_mode", "jwt"))
    integration_token = getattr(request.state, "integration_token", None)
    if integration_token is None:
        return IntegrationTokenTestResponse(ok=True, auth_mode=auth_mode)

    return IntegrationTokenTestResponse(
        ok=True,
        auth_mode=auth_mode,
        token_id=integration_token.id,
        token_name=integration_token.name,
        owner_user_id=integration_token.created_by_user_id,
    )
