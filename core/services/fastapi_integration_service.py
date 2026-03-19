from __future__ import annotations

from typing import Any
from uuid import UUID

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
        FastAPIIntegrationService._sync_known_tokens_status(config=config)
        FastAPIIntegrationService._ensure_selected_token_consistency(config=config)
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
    def register_existing_token(
        *,
        config: FastAPIIntegrationConfig,
        name: str,
        integration_token: str,
    ) -> FastAPIIntegrationToken:
        token_name = str(name or "").strip()[:120]
        raw_token = str(integration_token or "").strip()
        if len(token_name) < 3:
            raise FastAPIIntegrationServiceError("Informe um nome de token com ao menos 3 caracteres.")
        if len(raw_token) < 10:
            raise FastAPIIntegrationServiceError("Token de integracao invalido.")

        token_info = FastAPIIntegrationService._inspect_admin_token(
            config=config,
            integration_token=raw_token,
        )
        external_token_id = FastAPIIntegrationService._parse_uuid(token_info.get("token_id"))
        remote_name = str(token_info.get("token_name") or "").strip()[:120]
        resolved_name = remote_name or token_name

        with transaction.atomic():
            token = None
            if external_token_id is not None:
                token = FastAPIIntegrationService._find_token_by_external_id(
                    config=config,
                    external_token_id=external_token_id,
                )
            if token is None:
                token = FastAPIIntegrationToken.objects.filter(
                    config_id=config.id,
                    integration_token=raw_token,
                ).first()

            if token is None:
                token = FastAPIIntegrationToken.objects.create(
                    config_id=config.id,
                    external_token_id=external_token_id,
                    name=resolved_name,
                    integration_token=raw_token,
                    is_active=True,
                )
            else:
                changed_fields: list[str] = []
                if token.external_token_id != external_token_id:
                    token.external_token_id = external_token_id
                    changed_fields.append("external_token_id")
                if token.name != resolved_name:
                    token.name = resolved_name
                    changed_fields.append("name")
                if token.integration_token != raw_token:
                    token.integration_token = raw_token
                    changed_fields.append("integration_token")
                if not token.is_active:
                    token.is_active = True
                    changed_fields.append("is_active")
                if changed_fields:
                    token.save(update_fields=[*changed_fields, "updated_at"])

            config.selected_integration_token = token
            config.save(update_fields=["selected_integration_token", "updated_at"])

        return token

    @staticmethod
    def create_token_via_api(
        *,
        config: FastAPIIntegrationConfig,
        name: str,
    ) -> tuple[FastAPIIntegrationToken, str]:
        token_name = str(name or "").strip()
        if len(token_name) < 3:
            raise FastAPIIntegrationServiceError("Informe um nome de token com ao menos 3 caracteres.")

        payload = FastAPIIntegrationService._request_admin_api(
            config=config,
            method="POST",
            path="/api/v1/admin/integration-tokens",
            json_body={"name": token_name},
        )
        if not isinstance(payload, dict):
            raise FastAPIIntegrationServiceError("Resposta invalida da FastAPI ao criar token.")

        raw_token = str(payload.get("token") or "").strip()
        returned_name = str(payload.get("name") or token_name).strip()[:120]
        is_active = bool(payload.get("is_active", True))
        external_token_id = FastAPIIntegrationService._parse_uuid(payload.get("id"))
        if not raw_token:
            raise FastAPIIntegrationServiceError("Resposta da FastAPI nao trouxe o token gerado.")

        with transaction.atomic():
            created = None
            if external_token_id is not None:
                created = FastAPIIntegrationService._find_token_by_external_id(
                    config=config,
                    external_token_id=external_token_id,
                )

            if created is None:
                created = FastAPIIntegrationToken.objects.create(
                    config_id=config.id,
                    external_token_id=external_token_id,
                    name=returned_name,
                    integration_token=raw_token,
                    is_active=is_active,
                )
            else:
                created.external_token_id = external_token_id
                created.name = returned_name
                created.integration_token = raw_token
                created.is_active = is_active
                created.save(
                    update_fields=[
                        "external_token_id",
                        "name",
                        "integration_token",
                        "is_active",
                        "updated_at",
                    ]
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

        if is_active and token.external_token_id is not None:
            remote_is_active = FastAPIIntegrationService._is_token_active_in_fastapi(
                config=config,
                external_token_id=token.external_token_id,
            )
            if remote_is_active is False:
                raise FastAPIIntegrationServiceError(
                    "Este token ja foi revogado na FastAPI e nao pode ser reativado. Gere um novo token."
                )

        if not is_active:
            FastAPIIntegrationService._deactivate_token_in_fastapi(config=config, token=token)

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
    def _resolve_base_url(*, config: FastAPIIntegrationConfig) -> str:
        base_url = str(config.base_url or "").strip().rstrip("/")
        if not base_url:
            base_url = str(getattr(settings, "FASTAPI_BASE_URL", "http://127.0.0.1:8000")).strip().rstrip("/")
        if not base_url:
            raise FastAPIIntegrationServiceError("Base URL da FastAPI nao configurada.")
        return base_url

    @staticmethod
    def _resolve_timeout(timeout_seconds: float | None = None) -> float:
        if timeout_seconds is not None:
            return float(timeout_seconds)
        return float(getattr(settings, "FASTAPI_TIMEOUT_SECONDS", 2.5))

    @staticmethod
    def _resolve_admin_token_value(
        *,
        config: FastAPIIntegrationConfig,
        allow_legacy_fallback: bool = True,
    ) -> str:
        admin_token = FastAPIIntegrationService.get_selected_token_value(config=config)
        if admin_token:
            return admin_token

        if allow_legacy_fallback:
            legacy_token = str(getattr(settings, "FASTAPI_ADMIN_TOKEN", "") or "").strip()
            if legacy_token:
                return legacy_token

        raise FastAPIIntegrationServiceError(
            "Nao ha token de autenticacao administrativa disponivel. "
            "Cadastre o token bootstrap na tela de integracao da FastAPI."
        )

    @staticmethod
    def _parse_error_message(payload: Any) -> str:
        if isinstance(payload, dict):
            error_payload = payload.get("error")
            if isinstance(error_payload, dict):
                message = str(error_payload.get("message") or "").strip()
                if message:
                    return message
        return ""

    @staticmethod
    def _parse_uuid(value: Any) -> UUID | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return UUID(raw)
        except ValueError:
            return None

    @staticmethod
    def _request_admin_api(
        *,
        config: FastAPIIntegrationConfig,
        method: str,
        path: str,
        token_value: str | None = None,
        json_body: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        allow_legacy_fallback: bool = True,
    ) -> Any:
        timeout = FastAPIIntegrationService._resolve_timeout(timeout_seconds=timeout_seconds)
        base_url = FastAPIIntegrationService._resolve_base_url(config=config)
        admin_token = (
            str(token_value or "").strip()
            if token_value is not None
            else FastAPIIntegrationService._resolve_admin_token_value(
                config=config,
                allow_legacy_fallback=allow_legacy_fallback,
            )
        )
        if not admin_token:
            raise FastAPIIntegrationServiceError("Token administrativo vazio para chamada na FastAPI.")

        normalized_method = method.upper()
        normalized_path = "/" + str(path or "").lstrip("/")
        url = f"{base_url}{normalized_path}"
        headers = {"Authorization": f"Bearer {admin_token}"}

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.request(
                    normalized_method,
                    url,
                    headers=headers,
                    json=json_body,
                )
        except httpx.TimeoutException as exc:
            raise FastAPIIntegrationServiceError(
                f"Tempo limite excedido ao chamar FastAPI ({normalized_method} {normalized_path})."
            ) from exc
        except httpx.RequestError as exc:
            raise FastAPIIntegrationServiceError(
                f"Falha de conexao ao chamar FastAPI ({normalized_method} {normalized_path})."
            ) from exc

        payload: Any = None
        if response.status_code != 204:
            try:
                payload = response.json()
            except ValueError:
                payload = None

        if response.status_code >= 400:
            error_message = FastAPIIntegrationService._parse_error_message(payload)
            if not error_message:
                error_message = f"FastAPI retornou HTTP {response.status_code} em {normalized_path}."
            raise FastAPIIntegrationServiceError(error_message)

        if payload is None:
            return {}
        if isinstance(payload, (dict, list)):
            return payload

        raise FastAPIIntegrationServiceError(f"Resposta invalida da FastAPI em {normalized_path}.")

    @staticmethod
    def _find_token_by_external_id(
        *,
        config: FastAPIIntegrationConfig,
        external_token_id: UUID,
    ) -> FastAPIIntegrationToken | None:
        return FastAPIIntegrationToken.objects.filter(
            config_id=config.id,
            external_token_id=external_token_id,
        ).first()

    @staticmethod
    def _inspect_admin_token(
        *,
        config: FastAPIIntegrationConfig,
        integration_token: str,
    ) -> dict[str, Any]:
        payload = FastAPIIntegrationService._request_admin_api(
            config=config,
            method="GET",
            path="/api/v1/admin/integration-tokens/test",
            token_value=integration_token,
            allow_legacy_fallback=False,
        )
        if not isinstance(payload, dict):
            raise FastAPIIntegrationServiceError("Resposta invalida da FastAPI ao validar token bootstrap.")
        if not bool(payload.get("ok")):
            raise FastAPIIntegrationServiceError("Token bootstrap rejeitado pela FastAPI.")
        return payload

    @staticmethod
    def _deactivate_token_in_fastapi(
        *,
        config: FastAPIIntegrationConfig,
        token: FastAPIIntegrationToken,
    ) -> None:
        if token.external_token_id is None:
            token_info = FastAPIIntegrationService._inspect_admin_token(
                config=config,
                integration_token=str(token.integration_token or "").strip(),
            )
            external_token_id = FastAPIIntegrationService._parse_uuid(token_info.get("token_id"))
            if external_token_id is None:
                raise FastAPIIntegrationServiceError(
                    "Nao foi possivel identificar o token na FastAPI para revogacao."
                )
            token.external_token_id = external_token_id
            remote_name = str(token_info.get("token_name") or "").strip()[:120]
            changed_fields = ["external_token_id"]
            if remote_name and token.name != remote_name:
                token.name = remote_name
                changed_fields.append("name")
            token.save(update_fields=[*changed_fields, "updated_at"])

        path = f"/api/v1/admin/integration-tokens/{token.external_token_id}/deactivate"
        payload = FastAPIIntegrationService._request_admin_api(
            config=config,
            method="PATCH",
            path=path,
            token_value=str(token.integration_token or "").strip(),
            allow_legacy_fallback=False,
        )
        if isinstance(payload, dict) and bool(payload.get("is_active", False)):
            raise FastAPIIntegrationServiceError("Falha ao revogar token na FastAPI.")

    @staticmethod
    def _is_token_active_in_fastapi(
        *,
        config: FastAPIIntegrationConfig,
        external_token_id: UUID,
    ) -> bool | None:
        try:
            payload = FastAPIIntegrationService._request_admin_api(
                config=config,
                method="GET",
                path="/api/v1/admin/integration-tokens",
            )
        except FastAPIIntegrationServiceError:
            return None

        if not isinstance(payload, list):
            return None

        for item in payload:
            if not isinstance(item, dict):
                continue
            item_id = FastAPIIntegrationService._parse_uuid(item.get("id"))
            if item_id == external_token_id:
                return bool(item.get("is_active", False))
        return None

    @staticmethod
    def _sync_known_tokens_status(*, config: FastAPIIntegrationConfig) -> None:
        known_tokens = list(
            FastAPIIntegrationToken.objects.filter(
                config_id=config.id,
                external_token_id__isnull=False,
            )
        )
        if not known_tokens:
            return

        try:
            payload = FastAPIIntegrationService._request_admin_api(
                config=config,
                method="GET",
                path="/api/v1/admin/integration-tokens",
            )
        except FastAPIIntegrationServiceError:
            return

        if not isinstance(payload, list):
            return

        remote_map: dict[UUID, dict[str, Any]] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            item_id = FastAPIIntegrationService._parse_uuid(item.get("id"))
            if item_id is not None:
                remote_map[item_id] = item

        for token in known_tokens:
            external_id = token.external_token_id
            if external_id is None:
                continue
            remote_item = remote_map.get(external_id)
            if remote_item is None:
                continue

            changed_fields: list[str] = []
            remote_name = str(remote_item.get("name") or "").strip()[:120]
            remote_is_active = bool(remote_item.get("is_active", False))
            if remote_name and token.name != remote_name:
                token.name = remote_name
                changed_fields.append("name")
            if token.is_active != remote_is_active:
                token.is_active = remote_is_active
                changed_fields.append("is_active")
            if changed_fields:
                token.save(update_fields=[*changed_fields, "updated_at"])

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
