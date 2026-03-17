from contextvars import ContextVar, Token
from typing import Any

_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
_execution_id_ctx: ContextVar[str | None] = ContextVar("execution_id", default=None)
_provider_ctx: ContextVar[str | None] = ContextVar("provider", default=None)
_model_ctx: ContextVar[str | None] = ContextVar("model", default=None)


def bind_log_context(
    *,
    correlation_id: str | None = None,
    request_id: str | None = None,
    execution_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Token]:
    tokens: dict[str, Token] = {}
    if correlation_id is not None:
        tokens["correlation_id"] = _correlation_id_ctx.set(correlation_id)
    if request_id is not None:
        tokens["request_id"] = _request_id_ctx.set(request_id)
    if execution_id is not None:
        tokens["execution_id"] = _execution_id_ctx.set(execution_id)
    if provider is not None:
        tokens["provider"] = _provider_ctx.set(provider)
    if model is not None:
        tokens["model"] = _model_ctx.set(model)
    return tokens


def reset_log_context(tokens: dict[str, Token]) -> None:
    if token := tokens.get("correlation_id"):
        _correlation_id_ctx.reset(token)
    if token := tokens.get("request_id"):
        _request_id_ctx.reset(token)
    if token := tokens.get("execution_id"):
        _execution_id_ctx.reset(token)
    if token := tokens.get("provider"):
        _provider_ctx.reset(token)
    if token := tokens.get("model"):
        _model_ctx.reset(token)


def get_log_context() -> dict[str, Any]:
    return {
        "correlation_id": _correlation_id_ctx.get(),
        "request_id": _request_id_ctx.get(),
        "execution_id": _execution_id_ctx.get(),
        "provider": _provider_ctx.get(),
        "model": _model_ctx.get(),
    }
