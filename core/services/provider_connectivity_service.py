from __future__ import annotations

from typing import Any

from providers.models import Provider

from .api_client import FastAPIClient


class ProviderConnectivityClientService:
    def __init__(self) -> None:
        self.client = FastAPIClient()

    def test_provider_connectivity(self, *, provider: Provider) -> dict[str, Any]:
        if provider.fastapi_provider_id is None:
            return {
                "ok": False,
                "status": "provider_not_synced",
                "status_label": "Provider nao sincronizado",
                "message": (
                    "Provider local sem vinculo com a FastAPI. "
                    "Edite/salve o provider para sincronizar e gerar o ID remoto."
                ),
                "provider_id": provider.id,
                "provider_slug": provider.slug,
                "checks": [],
                "error_code": "provider_not_synced",
            }

        result = self.client.request_json(
            method="POST",
            path=f"/api/v1/admin/providers/{provider.fastapi_provider_id}/connectivity-test",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )

        if result.is_success and isinstance(result.data, dict):
            return {
                "ok": bool(result.data.get("ok")),
                "status": str(result.data.get("status") or "unknown"),
                "status_label": str(result.data.get("status_label") or "Status desconhecido"),
                "message": str(result.data.get("message") or ""),
                "provider_id": provider.id,
                "provider_slug": provider.slug,
                "checks": result.data.get("checks", []),
                "error_code": str(result.data.get("error_code") or "") or None,
            }

        payload_error = self._extract_error(result.data)
        if result.status_code == 404:
            return {
                "ok": False,
                "status": "provider_remote_not_found",
                "status_label": "Provider remoto inexistente",
                "message": payload_error or "Provider remoto nao encontrado na FastAPI.",
                "provider_id": provider.id,
                "provider_slug": provider.slug,
                "checks": [],
                "error_code": "provider_not_found",
            }
        if result.status_code in {401, 403}:
            return {
                "ok": False,
                "status": "admin_auth_error",
                "status_label": "Falha de autenticacao",
                "message": payload_error or "Falha de autenticacao administrativa com a FastAPI.",
                "provider_id": provider.id,
                "provider_slug": provider.slug,
                "checks": [],
                "error_code": "admin_auth_error",
            }
        if result.status_code is None:
            return {
                "ok": False,
                "status": "integration_error",
                "status_label": "Falha de integracao",
                "message": result.error or "Falha de integracao ao chamar FastAPI.",
                "provider_id": provider.id,
                "provider_slug": provider.slug,
                "checks": [],
                "error_code": "integration_error",
            }

        return {
            "ok": False,
            "status": "integration_error",
            "status_label": "Falha de integracao",
            "message": payload_error or f"FastAPI retornou HTTP {result.status_code} no teste de conectividade.",
            "provider_id": provider.id,
            "provider_slug": provider.slug,
            "checks": [],
            "error_code": "integration_error",
        }

    @staticmethod
    def _extract_error(data: Any) -> str:
        if isinstance(data, dict):
            error_payload = data.get("error")
            if isinstance(error_payload, dict):
                return str(error_payload.get("message") or "").strip()
        return ""
