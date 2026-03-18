from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings


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
    def __init__(self, *, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or settings.FASTAPI_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.FASTAPI_TIMEOUT_SECONDS

    def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expect_dict: bool = True,
    ) -> ApiResponse:
        url = f"{self.base_url}/{path.lstrip('/')}"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, params=params, headers=headers)
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
