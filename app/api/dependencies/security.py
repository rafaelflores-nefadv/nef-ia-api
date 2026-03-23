from dataclasses import dataclass
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import Depends, Request

from app.core.exceptions import AppException
from app.models.operational import DjangoAiApiToken, DjangoAiApiTokenPermission, DjangoAiUser
from app.services.token_service import check_token_permission


@dataclass(slots=True)
class TokenScope:
    token: DjangoAiApiToken
    token_id: UUID


def get_current_admin_user(request: Request) -> DjangoAiUser:
    user = getattr(request.state, "admin_user", None)
    if user is None:
        raise AppException("Administrative authentication required.", status_code=401, code="admin_auth_required")
    return user


def get_current_token(request: Request) -> DjangoAiApiToken:
    token = getattr(request.state, "api_token", None)
    if token is None:
        raise AppException("API token authentication required.", status_code=401, code="api_token_required")
    return token


def get_current_token_scope(token: DjangoAiApiToken = Depends(get_current_token)) -> TokenScope:
    return TokenScope(token=token, token_id=token.id)


def _extract_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None


def require_permission(
    operation: str,
    *,
    automation_id_key: str = "automation_id",
    provider_id_key: str = "provider_id",
) -> Callable:
    def dependency(
        request: Request,
        _: DjangoAiApiToken = Depends(get_current_token),
    ) -> None:
        permissions: list[DjangoAiApiTokenPermission] = getattr(request.state, "token_permissions", [])
        automation_id = _extract_uuid(request.path_params.get(automation_id_key) or request.query_params.get(automation_id_key))
        provider_id = _extract_uuid(request.path_params.get(provider_id_key) or request.query_params.get(provider_id_key))

        allowed = check_token_permission(
            permissions=permissions,
            operation=operation,
            automation_id=automation_id,
            provider_id=provider_id,
        )
        if not allowed:
            raise AppException("Token does not have required permission.", status_code=403, code="permission_denied")

    return dependency

