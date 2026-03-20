from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .api_client import ApiResponse, FastAPIClient


@dataclass
class PromptCatalogEndpointProbe:
    path: str
    method: str
    status_code: int | None
    ok: bool
    exists: bool
    message: str


class PromptsCatalogAPIService:
    """
    Diagnose whether FastAPI already exposes an official prompts catalog/admin API.

    Architecture target:
    - prompts should be managed by the API/source-of-truth
    - local Django prompt model remains transitional while endpoints do not exist
    """

    CANDIDATE_ENDPOINTS: tuple[tuple[str, str], ...] = (
        ("/api/v1/admin/prompts", "GET"),
        ("/api/v1/admin/automation-prompts", "GET"),
        ("/api/v1/admin/automations", "GET"),
    )

    REQUIRED_BACKEND_NOTES: tuple[str, ...] = (
        "Backend deve expor endpoints administrativos oficiais para prompts/automacoes.",
        "Estrutura esperada: automations + automation_prompts como fonte oficial.",
        "CRUD local Django permanece apenas legado/transicao ate disponibilidade dos endpoints.",
    )

    def __init__(self, *, client: FastAPIClient | None = None) -> None:
        self.client = client or FastAPIClient()

    @staticmethod
    def _extract_error_message(result: ApiResponse) -> str:
        if isinstance(result.data, dict):
            error_payload = result.data.get("error")
            if isinstance(error_payload, dict):
                payload_message = str(error_payload.get("message") or "").strip()
                if payload_message:
                    return payload_message
        return str(result.error or "").strip()

    def _probe_endpoint(self, *, path: str, method: str) -> PromptCatalogEndpointProbe:
        result = self.client.request_json(
            method=method,
            path=path,
            headers=self.client.get_admin_headers(),
            expect_dict=False,
        )
        status_code = result.status_code
        message = self._extract_error_message(result)
        ok = bool(result.is_success)
        exists = bool(status_code not in {None, 404})

        if status_code == 404:
            message = message or "Endpoint nao encontrado na FastAPI."
        elif status_code is None:
            message = message or "Falha de comunicacao com a FastAPI."
        elif ok and not message:
            message = "Endpoint disponivel."
        elif not message:
            message = f"FastAPI retornou HTTP {status_code}."

        return PromptCatalogEndpointProbe(
            path=path,
            method=method,
            status_code=status_code,
            ok=ok,
            exists=exists,
            message=message,
        )

    def diagnose_catalog(self) -> dict[str, Any]:
        probes = [
            self._probe_endpoint(path=path, method=method)
            for path, method in self.CANDIDATE_ENDPOINTS
        ]

        has_official_catalog_api = any(probe.ok for probe in probes)
        blocked_by_auth = any(probe.status_code in {401, 403} for probe in probes)
        unreachable = any(probe.status_code is None for probe in probes)
        all_not_found = bool(probes) and all(probe.status_code == 404 for probe in probes)

        warnings: list[str] = []
        if has_official_catalog_api:
            source = "api"
            mode = "api"
        else:
            source = "fallback_local"
            mode = "transition_local_legacy"

            if all_not_found:
                warnings.append(
                    "FastAPI ainda nao expoe endpoint oficial de catalogo de prompts/automacoes."
                )
            elif blocked_by_auth:
                warnings.append(
                    "Nao foi possivel confirmar catalogo remoto de prompts por falha de autenticacao/permissao."
                )
            elif unreachable:
                warnings.append(
                    "Nao foi possivel confirmar catalogo remoto de prompts por falha de conectividade."
                )
            else:
                warnings.append("Catalogo remoto de prompts indisponivel no backend atual.")

            warnings.extend(self.REQUIRED_BACKEND_NOTES)

        return {
            "source": source,
            "mode": mode,
            "remote_available": has_official_catalog_api,
            "warnings": warnings,
            "required_backend_notes": list(self.REQUIRED_BACKEND_NOTES),
            "endpoint_probes": [
                {
                    "path": probe.path,
                    "method": probe.method,
                    "status_code": probe.status_code,
                    "ok": probe.ok,
                    "exists": probe.exists,
                    "message": probe.message,
                }
                for probe in probes
            ],
        }
