import uuid

from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.log_context import bind_log_context, reset_log_context


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        incoming_correlation_id = request.headers.get("X-Correlation-ID")
        incoming_request_id = request.headers.get("X-Request-ID")
        correlation_id = incoming_correlation_id or incoming_request_id or str(uuid.uuid4())
        request_id = incoming_request_id or correlation_id

        request.state.correlation_id = correlation_id
        request.state.request_id = request_id

        tokens = bind_log_context(
            correlation_id=correlation_id,
            request_id=request_id,
        )
        try:
            response = await call_next(request)
        finally:
            reset_log_context(tokens)

        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Request-ID"] = request_id
        return response
