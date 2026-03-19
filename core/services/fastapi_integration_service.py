from __future__ import annotations

from typing import Any

import httpx
from django.conf import settings
from django.db import transaction

from core.models import FastAPIIntegrationConfig, FastAPIIntegrationToken


class FastAPIIntegrationServiceError(Exception):
    pass


class FastAPIIntegrationService:
    @staticmethod
    def get_or_create_config() -> FastAPIIntegrationConfig:
        config, _ = FastAPIIntegrationConfig.objects.get_or_create(
            pk=1,
            defaults={
                "base_url": str(getattr(settings, "FASTAPI_BASE_URL", "http://127.0.0.1:8000")).rstrip("/"),
                "is_active": True,
            },
        )
        if config.base_url:
            normalized = config.base_url.rstrip("/")
            if normalized != config.base_url:
                config.base_url = normalized
                config.save(update_fields=["base_url", "updated_at"])

        FastAPIIntegrationService._ensure_selected_token_consistency(config=config)
        return config

    @staticmethod
    def list_tokens(*, config: FastAPIIntegrationConfig) -> list[FastAPIIntegrationToken]:
        return list(
            FastAPIIntegrationToken.objects.filter(config_id=config.id).order_by("-updated_at", "-id")
        )

    @staticmethod
    def get_selected_token(
        *,
        config: FastAPIIntegrationConfig,
        active_only: bool = False,
    ) -> FastAPIIntegrationToken | None:
        selected_token = None
        selected_token_id = config.selected_integration_token_id
        if selected_token_id:
            selected_token = FastAPIIntegrationToken.objects.filter(
                id=selected_token_id,
                config_id=config.id,
            ).first()

        if selected_token is None and not active_only:
            return None
        if selected_token is None and active_only:
            return FastAPIIntegrationToken.objects.filter(
                config_id=config.id,
                is_active=True,
            ).order_by("-updated_at", "-id").first()
        if active_only and not selected_token.is_active:
            return FastAPIIntegrationToken.objects.filter(
                config_id=config.id,
                is_active=True,
            ).order_by("-updated_at", "-id").first()
        return selected_token

    @staticmethod
    def get_selected_token_value(*, config: FastAPIIntegrationConfig) -> str:
        selected_token = FastAPIIntegrationService.get_selected_token(
            config=config,
            active_only=True,
        )
        if selected_token is None:
            return ""
        return str(selected_token.integration_token or "").strip()

    @staticmethod
    def create_token_via_api(
        *,
        config: FastAPIIntegrationConfig,
        name: str,
    ) -> tuple[FastAPIIntegrationToken, str]:
        token_name = str(name or "").strip()
        if len(token_name) < 3:
            raise FastAPIIntegrationServiceError("Informe um nome de token com ao menos 3 caracteres.")

        timeout = float(getattr(settings, "FASTAPI_TIMEOUT_SECONDS", 2.5))
        base_url = str(config.base_url or "").strip().rstrip("/")
        if not base_url:
            base_url = str(getattr(settings, "FASTAPI_BASE_URL", "http://127.0.0.1:8000")).strip().rstrip("/")
        if not base_url:
            raise FastAPIIntegrationServiceError("Base URL da FastAPI nao configurada.")

        admin_token = FastAPIIntegrationService.get_selected_token_value(config=config)
        if not admin_token:
            admin_token = str(getattr(settings, "FASTAPI_ADMIN_TOKEN", "") or "").strip()
        if not admin_token:
            raise FastAPIIntegrationServiceError(
                "Nao ha token de autenticacao para criar novo token na FastAPI."
            )

        url = f"{base_url}/api/v1/admin/integration-tokens"
        headers = {"Authorization": f"Bearer {admin_token}"}

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    url,
                    headers=headers,
                    json={"name": token_name},
                )
        except httpx.TimeoutException as exc:
            raise FastAPIIntegrationServiceError(
                "Tempo limite excedido ao solicitar novo token na FastAPI."
            ) from exc
        except httpx.RequestError as exc:
            raise FastAPIIntegrationServiceError(
                "Falha de conexao ao solicitar novo token na FastAPI."
            ) from exc

        payload: dict[str, Any] = {}
        try:
            decoded = response.json()
            if isinstance(decoded, dict):
                payload = decoded
        except ValueError:
            payload = {}

        if response.status_code >= 400:
            error_message = ""
            if isinstance(payload.get("error"), dict):
                error_message = str(payload["error"].get("message") or "").strip()
            if not error_message:
                error_message = f"FastAPI retornou HTTP {response.status_code} ao criar token."
            raise FastAPIIntegrationServiceError(error_message)

        raw_token = str(payload.get("token") or "").strip()
        returned_name = str(payload.get("name") or token_name).strip()[:120]
        is_active = bool(payload.get("is_active", True))
        if not raw_token:
            raise FastAPIIntegrationServiceError("Resposta da FastAPI nao trouxe o token gerado.")

        with transaction.atomic():
            created = FastAPIIntegrationToken.objects.create(
                config_id=config.id,
                name=returned_name,
                integration_token=raw_token,
                is_active=is_active,
            )
            config.selected_integration_token = created
            config.save(update_fields=["selected_integration_token", "updated_at"])

        return created, raw_token

    @staticmethod
    def select_token(
        *,
        config: FastAPIIntegrationConfig,
        token_id: int,
    ) -> FastAPIIntegrationToken:
        token = FastAPIIntegrationToken.objects.filter(
            id=token_id,
            config_id=config.id,
        ).first()
        if token is None:
            raise FastAPIIntegrationServiceError("Token informado nao foi encontrado.")
        if not token.is_active:
            raise FastAPIIntegrationServiceError("Nao e possivel selecionar um token inativo.")

        config.selected_integration_token = token
        config.save(update_fields=["selected_integration_token", "updated_at"])
        return token

    @staticmethod
    def set_token_status(
        *,
        config: FastAPIIntegrationConfig,
        token_id: int,
        is_active: bool,
    ) -> FastAPIIntegrationToken:
        token = FastAPIIntegrationToken.objects.filter(
            id=token_id,
            config_id=config.id,
        ).first()
        if token is None:
            raise FastAPIIntegrationServiceError("Token informado nao foi encontrado.")

        if token.is_active != is_active:
            token.is_active = is_active
            token.save(update_fields=["is_active", "updated_at"])

        if not is_active and config.selected_integration_token_id == token.id:
            replacement = FastAPIIntegrationToken.objects.filter(
                config_id=config.id,
                is_active=True,
            ).exclude(id=token.id).order_by("-updated_at", "-id").first()
            config.selected_integration_token = replacement
            config.save(update_fields=["selected_integration_token", "updated_at"])

        if is_active and config.selected_integration_token_id is None:
            config.selected_integration_token = token
            config.save(update_fields=["selected_integration_token", "updated_at"])

        return token

    @staticmethod
    def _ensure_selected_token_consistency(*, config: FastAPIIntegrationConfig) -> None:
        selected = FastAPIIntegrationService.get_selected_token(config=config)
        if selected is not None and selected.is_active:
            return

        replacement = FastAPIIntegrationToken.objects.filter(
            config_id=config.id,
            is_active=True,
        ).order_by("-updated_at", "-id").first()

        if config.selected_integration_token_id != (replacement.id if replacement else None):
            config.selected_integration_token = replacement
            config.save(update_fields=["selected_integration_token", "updated_at"])

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
