from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings
from django.db import DatabaseError
from django.db.utils import OperationalError, ProgrammingError


@dataclass
class ApiResponse:
    status_code: int | None
    data: Any | None
    error: str | None = None

    @property
    def is_reachable(self) -> bool:
        return self.status_code is not None

    @property
    def is_success(self) -> bool:
        return (
            self.status_code is not None
            and 200 <= self.status_code < 300
            and self.data is not None
        )


class FastAPIClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        admin_token: str | None = None,
        integration_active: bool | None = None,
    ):
        self.timeout = timeout if timeout is not None else settings.FASTAPI_TIMEOUT_SECONDS
        runtime_config = self._resolve_runtime_config(
            base_url=base_url,
            admin_token=admin_token,
            integration_active=integration_active,
        )
        self.base_url = runtime_config["base_url"].rstrip("/")
        self.admin_token = runtime_config["admin_token"]
        self.integration_active = runtime_config["integration_active"]

    def _resolve_runtime_config(
        self,
        *,
        base_url: str | None,
        admin_token: str | None,
        integration_active: bool | None,
    ) -> dict[str, Any]:
        resolved_base_url = str(
            base_url
            or getattr(settings, "FASTAPI_BASE_URL", "http://127.0.0.1:8000")
            or "http://127.0.0.1:8000"
        ).strip()
        resolved_admin_token = str(
            admin_token
            if admin_token is not None
            else (getattr(settings, "FASTAPI_ADMIN_TOKEN", "") or "")
        ).strip()
        resolved_integration_active = (
            bool(integration_active) if integration_active is not None else True
        )

        db_config = self._load_db_integration_config()
        if db_config is not None:
            if base_url is None:
                db_base_url = str(db_config.get("base_url") or "").strip()
                if db_base_url:
                    resolved_base_url = db_base_url
            if admin_token is None:
                resolved_admin_token = str(db_config.get("integration_token") or "").strip()
            if integration_active is None:
                resolved_integration_active = bool(db_config.get("is_active", True))

        return {
            "base_url": resolved_base_url or "http://127.0.0.1:8000",
            "admin_token": resolved_admin_token,
            "integration_active": resolved_integration_active,
        }

    def _load_db_integration_config(self) -> dict[str, Any] | None:
        try:
            from core.models import FastAPIIntegrationConfig

            config = FastAPIIntegrationConfig.objects.filter(pk=1).first()
            if config is None:
                config = FastAPIIntegrationConfig.objects.order_by("-updated_at").first()
            if config is None:
                return None
            return {
                "base_url": config.base_url,
                "integration_token": config.integration_token,
                "is_active": config.is_active,
            }
        except (OperationalError, ProgrammingError, DatabaseError):
            return None

    def get_admin_headers(self) -> dict[str, str] | None:
        if not self.admin_token:
            return None
        return {"Authorization": f"Bearer {self.admin_token}"}

    def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expect_dict: bool = True,
    ) -> ApiResponse:
        if not self.integration_active:
            return ApiResponse(
                status_code=None,
                data=None,
                error="Integracao FastAPI desativada nas configuracoes.",
            )

        url = f"{self.base_url}/{path.lstrip('/')}"
        resolved_headers = headers
        if resolved_headers is None and path.startswith("/api/v1/admin"):
            resolved_headers = self.get_admin_headers()

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, params=params, headers=resolved_headers)
        except httpx.TimeoutException:
            return ApiResponse(
                status_code=None,
                data=None,
                error="Tempo limite excedido ao consultar a FastAPI.",
            )
        except httpx.RequestError:
            return ApiResponse(
                status_code=None,
                data=None,
                error="Falha de conexao com a FastAPI.",
            )

        try:
            decoded = response.json()
        except ValueError:
            return ApiResponse(
                status_code=response.status_code,
                data=None,
                error=f"Resposta nao JSON da FastAPI em {path}.",
            )

        if expect_dict and not isinstance(decoded, dict):
            return ApiResponse(
                status_code=response.status_code,
                data=None,
                error=f"Resposta invalida da FastAPI em {path}.",
            )

        if not expect_dict and not isinstance(decoded, (dict, list)):
            return ApiResponse(
                status_code=response.status_code,
                data=None,
                error=f"Resposta invalida da FastAPI em {path}.",
            )

        payload = decoded

        if response.status_code >= 400:
            payload_error = None
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                payload_error = payload["error"].get("message")
            return ApiResponse(
                status_code=response.status_code,
                data=payload,
                error=payload_error
                or f"FastAPI retornou HTTP {response.status_code} em {path}.",
            )

        return ApiResponse(status_code=response.status_code, data=payload, error=None)
