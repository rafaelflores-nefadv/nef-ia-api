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
)
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

