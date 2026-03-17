from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from app.core.config import get_settings
from app.core.exceptions import AppException

settings = get_settings()


def create_admin_jwt(*, user_id: str, role: str) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.admin_jwt_expire_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "user_id": user_id,
        "role": role,
        "type": "admin_access",
        "exp": expires_at,
    }
    encoded = jwt.encode(payload, settings.secret_key, algorithm=settings.admin_jwt_algorithm)
    return encoded, expires_at


def decode_admin_jwt(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.admin_jwt_algorithm])
    except ExpiredSignatureError as exc:
        raise AppException(
            "Administrative token expired.",
            status_code=401,
            code="admin_token_expired",
        ) from exc
    except InvalidTokenError as exc:
        raise AppException(
            "Invalid administrative token.",
            status_code=401,
            code="invalid_admin_token",
        ) from exc

    if payload.get("type") != "admin_access":
        raise AppException(
            "Invalid administrative token type.",
            status_code=401,
            code="invalid_admin_token_type",
        )
    return payload
