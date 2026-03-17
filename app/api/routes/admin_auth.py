from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_admin_user
from app.db.session import get_operational_session
from app.models.operational import DjangoAiUser
from app.schemas.admin_auth import AdminLoginRequest, AdminLoginResponse, AdminMeResponse
from app.services.auth_service import AuthService

router = APIRouter(tags=["admin-auth"])


@router.post("/auth/login", response_model=AdminLoginResponse)
def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    session: Session = Depends(get_operational_session),
) -> AdminLoginResponse:
    ip_address = request.client.host if request.client else None
    result = AuthService(session).login_admin(
        email=payload.email,
        password=payload.password,
        ip_address=ip_address,
    )
    return AdminLoginResponse(
        access_token=result.access_token,
        expires_at=result.expires_at,
    )


@router.get("/me", response_model=AdminMeResponse)
def admin_me(current_user: DjangoAiUser = Depends(get_current_admin_user)) -> AdminMeResponse:
    return AdminMeResponse(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        role=current_user.role.name if current_user.role else "unknown",
    )

