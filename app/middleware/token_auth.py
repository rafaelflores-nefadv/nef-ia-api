import logging
from dataclasses import asdict
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.log_context import bind_log_context, reset_log_context
from app.db.session import SessionLocal
from app.services.auth_service import AuthService
from app.services.token_service import ApiTokenService

logger = logging.getLogger(__name__)
settings = get_settings()


class TokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.api_prefix = settings.api_prefix
        self.admin_prefix = f"{self.api_prefix}/admin"
        self.admin_login_path = f"{self.api_prefix}/admin/auth/login"
        self.public_paths = {
            "/health",
            "/health/live",
            "/health/ready",
            "/docs",
            "/redoc",
            "/openapi.json",
            self.admin_login_path,
        }

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        path = request.url.path
        if request.method == "OPTIONS" or path in self.public_paths:
            return await call_next(request)

        if not path.startswith(self.api_prefix):
            return await call_next(request)

        try:
            bearer_token = self._extract_bearer_token(request)
            if path.startswith(self.admin_prefix):
                with SessionLocal() as session:
                    admin_user = AuthService(session).get_user_from_admin_jwt(bearer_token)
                    request.state.admin_user = admin_user
                return await call_next(request)
            return await self._authenticate_api_token_request(request, bearer_token, call_next)
        except AppException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": asdict(exc.payload)},
            )

    def _extract_bearer_token(self, request: Request) -> str:
        header = request.headers.get("Authorization")
        if not header:
            raise AppException("Missing Authorization header.", status_code=401, code="missing_authorization_header")

        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AppException("Invalid Authorization header format.", status_code=401, code="invalid_authorization_header")
        return token.strip()

    async def _authenticate_api_token_request(self, request: Request, raw_token: str, call_next) -> Response:  # type: ignore[no-untyped-def]
        with SessionLocal() as session:
            token_service = ApiTokenService(session)
            validation = token_service.validate_token(raw_token)
            request.state.api_token = validation.token
            request.state.token_permissions = validation.permissions

        execution_id = self._extract_execution_id(request)
        context_tokens = bind_log_context(execution_id=str(execution_id) if execution_id else None)
        response: Response | None = None
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            reset_log_context(context_tokens)
            self._log_token_usage(
                request=request,
                status_code=status_code,
                execution_id=execution_id or self._extract_execution_id(request),
            )

    def _extract_execution_id(self, request: Request) -> UUID | None:
        state_execution_id = getattr(request.state, "execution_id", None)
        if state_execution_id:
            try:
                return UUID(str(state_execution_id))
            except ValueError:
                return None

        path_param = request.path_params.get("execution_id") if request.path_params else None
        if path_param:
            try:
                return UUID(str(path_param))
            except ValueError:
                return None

        query_param = request.query_params.get("execution_id")
        if query_param:
            try:
                return UUID(query_param)
            except ValueError:
                return None
        return None

    def _log_token_usage(self, *, request: Request, status_code: int, execution_id: UUID | None) -> None:
        token = getattr(request.state, "api_token", None)
        token_id = token.id if token else None
        endpoint = request.url.path
        method = request.method
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        try:
            with SessionLocal() as session:
                ApiTokenService(session).log_token_usage(
                    token_id=token_id,
                    endpoint=endpoint,
                    method=method,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    status_code=status_code,
                    execution_id=execution_id,
                )
        except Exception:
            logger.exception("Failed to write API token usage log.")
