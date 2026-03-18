from __future__ import annotations

from typing import Any

import httpx
from django.conf import settings

from core.models import FastAPIIntegrationConfig


class FastAPIIntegrationService:
    @staticmethod
    def get_or_create_config() -> FastAPIIntegrationConfig:
        config, _ = FastAPIIntegrationConfig.objects.get_or_create(
            pk=1,
            defaults={
                "base_url": str(getattr(settings, "FASTAPI_BASE_URL", "http://127.0.0.1:8000")).rstrip("/"),
                "integration_token": str(getattr(settings, "FASTAPI_ADMIN_TOKEN", "") or "").strip(),
                "token_name": "",
                "is_active": True,
            },
        )
        if config.base_url:
            normalized = config.base_url.rstrip("/")
            if normalized != config.base_url:
                config.base_url = normalized
                config.save(update_fields=["base_url", "updated_at"])
        return config

    @staticmethod
    def test_connection(
        *,
        base_url: str,
        integration_token: str,
        is_active: bool,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if not is_active:
            return {
                "ok": False,
                "status": "disabled",
                "status_label": "Integracao desativada",
                "message": "Ative a integracao para realizar testes com a FastAPI.",
                "checks": [],
            }

        timeout = timeout_seconds if timeout_seconds is not None else float(
            getattr(settings, "FASTAPI_TIMEOUT_SECONDS", 2.5)
        )
        normalized_base = str(base_url or "").strip().rstrip("/")
        token = str(integration_token or "").strip()

        checks: list[dict[str, Any]] = []

        try:
            with httpx.Client(timeout=timeout) as client:
                live_resp = client.get(f"{normalized_base}/health/live")
                checks.append(
                    {
                        "name": "health_live",
                        "http_status": live_resp.status_code,
                        "ok": live_resp.status_code < 400,
                        "message": "Endpoint /health/live respondeu."
                        if live_resp.status_code < 400
                        else "Endpoint /health/live retornou erro.",
                    }
                )

                admin_headers = {"Authorization": f"Bearer {token}"} if token else {}
                providers_resp = client.get(
                    f"{normalized_base}/api/v1/admin/providers",
                    headers=admin_headers,
                )
                providers_ok = providers_resp.status_code < 400
                checks.append(
                    {
                        "name": "admin_providers",
                        "http_status": providers_resp.status_code,
                        "ok": providers_ok,
                        "message": "Endpoint administrativo respondeu."
                        if providers_ok
                        else "Endpoint administrativo retornou erro.",
                    }
                )
        except httpx.TimeoutException:
            return {
                "ok": False,
                "status": "error",
                "status_label": "Timeout",
                "message": "Tempo limite excedido ao conectar com a FastAPI.",
                "checks": checks,
            }
        except httpx.RequestError:
            return {
                "ok": False,
                "status": "error",
                "status_label": "Sem conexao",
                "message": "Falha de conexao com a FastAPI.",
                "checks": checks,
            }

        live_ok = bool(next((item["ok"] for item in checks if item["name"] == "health_live"), False))
        admin_ok = bool(next((item["ok"] for item in checks if item["name"] == "admin_providers"), False))

        if live_ok and admin_ok:
            return {
                "ok": True,
                "status": "online",
                "status_label": "Conectado",
                "message": "Conexao com FastAPI e autenticacao administrativa validadas.",
                "checks": checks,
            }
        if live_ok and not admin_ok:
            return {
                "ok": False,
                "status": "degraded",
                "status_label": "Conexao parcial",
                "message": "FastAPI responde, mas autenticacao administrativa falhou.",
                "checks": checks,
            }
        return {
            "ok": False,
            "status": "error",
            "status_label": "Indisponivel",
            "message": "FastAPI indisponivel para o endpoint de health.",
            "checks": checks,
        }
