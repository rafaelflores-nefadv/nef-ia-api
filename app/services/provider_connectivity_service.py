import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.repositories.operational import ProviderRepository
from app.services.provider_model_discovery_service import ProviderModelDiscoveryService
from app.services.providers.provider_resolution import (
    SUPPORTED_DISCOVERY_PROVIDER_CANONICAL_SLUGS,
    resolve_discovery_provider_slug,
)


class ProviderConnectivityService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.providers = ProviderRepository(session)
        self.discovery = ProviderModelDiscoveryService(session)

    def test_provider_connectivity(self, *, provider_id: uuid.UUID) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        provider = self.providers.get_by_id(provider_id)
        if provider is None:
            return self._failure(
                status="provider_not_found",
                status_label="Provider remoto inexistente",
                message="Provider remoto nao encontrado na FastAPI.",
                provider_id=provider_id,
                provider_slug=None,
                checks=checks,
                error_code="provider_not_found",
            )

        checks.append(
            {
                "name": "provider_exists",
                "ok": True,
                "message": "Provider remoto localizado na FastAPI.",
            }
        )

        if not provider.is_active:
            checks.append(
                {
                    "name": "provider_active",
                    "ok": False,
                    "message": "Provider remoto esta inativo na FastAPI.",
                    "code": "provider_inactive",
                }
            )
            return self._failure(
                status="provider_inactive",
                status_label="Provider remoto inativo",
                message="Provider remoto inativo na FastAPI.",
                provider_id=provider_id,
                provider_slug=provider.slug,
                checks=checks,
                error_code="provider_inactive",
            )

        checks.append(
            {
                "name": "provider_active",
                "ok": True,
                "message": "Provider remoto ativo.",
            }
        )

        credentials = self.providers.list_credentials(provider.id)
        if not credentials:
            checks.append(
                {
                    "name": "active_credential",
                    "ok": False,
                    "message": "Nao existe credencial cadastrada para o provider remoto.",
                    "code": "provider_credential_not_found",
                }
            )
            return self._failure(
                status="credential_not_found",
                status_label="Sem credencial ativa",
                message="Nao existe credencial cadastrada para este provider na FastAPI.",
                provider_id=provider_id,
                provider_slug=provider.slug,
                checks=checks,
                error_code="provider_credential_not_found",
            )
        credential = self.providers.get_active_credential(provider.id)
        if credential is None:
            checks.append(
                {
                    "name": "active_credential",
                    "ok": False,
                    "message": "Existem credenciais para o provider, mas nenhuma esta ativa.",
                    "code": "provider_credential_inactive",
                }
            )
            return self._failure(
                status="credential_inactive",
                status_label="Credencial inativa",
                message="Existe credencial cadastrada, mas nenhuma credencial ativa para o provider.",
                provider_id=provider_id,
                provider_slug=provider.slug,
                checks=checks,
                error_code="provider_credential_inactive",
            )

        checks.append(
            {
                "name": "active_credential",
                "ok": True,
                "message": "Credencial ativa localizada.",
            }
        )

        try:
            api_key = self.discovery._decrypt_credential_or_422(credential)
        except AppException as exc:
            checks.append(
                {
                    "name": "credential_decryption",
                    "ok": False,
                    "message": "Falha ao validar/descriptografar credencial ativa.",
                    "code": exc.payload.code,
                }
            )
            return self._failure(
                status="credential_invalid",
                status_label="Credencial invalida",
                message="Falha ao validar/descriptografar credencial ativa do provider.",
                provider_id=provider_id,
                provider_slug=provider.slug,
                checks=checks,
                error_code=exc.payload.code,
            )

        checks.append(
            {
                "name": "credential_decryption",
                "ok": True,
                "message": "Credencial ativa validada e descriptografada.",
            }
        )

        canonical_provider_slug = resolve_discovery_provider_slug(provider.slug)
        if canonical_provider_slug is None:
            checks.append(
                {
                    "name": "provider_support",
                    "ok": False,
                    "message": (
                        "Provider ainda sem suporte de teste automatico. "
                        "Atualmente o teste automatico esta disponivel para OpenAI, Anthropic/Claude e Gemini."
                    ),
                    "code": "provider_discovery_not_supported",
                }
            )
            return self._failure(
                status="provider_not_supported",
                status_label="Provider sem suporte de teste",
                message=(
                    "Provider ainda sem suporte de teste automatico. "
                    "No momento, o teste automatico cobre OpenAI, Anthropic/Claude e Gemini."
                ),
                provider_id=provider_id,
                provider_slug=provider.slug,
                checks=checks,
                error_code="provider_discovery_not_supported",
            )

        checks.append(
            {
                "name": "provider_support",
                "ok": True,
                "message": (
                    "Provider com suporte de teste automatico "
                    f"(backend: {canonical_provider_slug})."
                ),
            }
        )

        try:
            _, raw_models = self.discovery.fetch_raw_models(
                provider_slug=provider.slug,
                provider_id=provider.id,
                api_key=api_key,
                config_json=credential.config_json or {},
            )
        except AppException as exc:
            status, status_label, message = self._map_provider_error(exc)
            checks.append(
                {
                    "name": "provider_connectivity",
                    "ok": False,
                    "message": message,
                    "code": exc.payload.code,
                    "http_status": self._extract_http_status(exc),
                }
            )
            return self._failure(
                status=status,
                status_label=status_label,
                message=message,
                provider_id=provider_id,
                provider_slug=provider.slug,
                checks=checks,
                error_code=exc.payload.code,
            )

        checks.append(
            {
                "name": "provider_connectivity",
                "ok": True,
                "message": (
                    "Conectividade com provider validada com sucesso. "
                    f"Modelos retornados: {len(raw_models)}."
                ),
            }
        )
        return {
            "ok": True,
            "status": "connected",
            "status_label": "Conectado",
            "message": "Integracao validada com sucesso entre FastAPI e provider real.",
            "provider_id": provider.id,
            "provider_slug": provider.slug,
            "checks": checks,
            "error_code": None,
        }

    @staticmethod
    def _extract_http_status(exc: AppException) -> int | None:
        details = exc.payload.details
        if isinstance(details, dict):
            value = details.get("status_code")
            try:
                return int(value) if value is not None else None
            except (TypeError, ValueError):
                return None
        return None

    def _map_provider_error(self, exc: AppException) -> tuple[str, str, str]:
        code = exc.payload.code
        details = exc.payload.details if isinstance(exc.payload.details, dict) else {}
        http_status = details.get("status_code")
        if code == "provider_timeout":
            return (
                "provider_timeout",
                "Timeout no provider",
                "Tempo limite excedido ao conectar com o provider real.",
            )
        if code == "provider_network_error":
            return (
                "provider_network_error",
                "Falha de conectividade",
                "Falha de rede ao conectar com o provider real.",
            )
        if code == "provider_http_error":
            if int(http_status or 0) in {401, 403}:
                return (
                    "api_key_invalid",
                    "API key invalida",
                    "Provider rejeitou autenticacao. Verifique API key/permicoes.",
                )
            return (
                "provider_http_error",
                "Erro de integracao",
                f"Provider retornou erro HTTP {http_status or 'desconhecido'}.",
            )
        if code == "provider_discovery_not_supported":
            supported = ", ".join(sorted(SUPPORTED_DISCOVERY_PROVIDER_CANONICAL_SLUGS))
            return (
                "provider_not_supported",
                "Provider sem suporte",
                (
                    "Provider ainda sem suporte de descoberta/conectividade automatica. "
                    f"Suportados atualmente: {supported}."
                ),
            )
        if code == "provider_invalid_response":
            return (
                "provider_invalid_response",
                "Resposta invalida",
                "Provider retornou resposta invalida para o teste.",
            )
        return (
            "integration_error",
            "Falha de integracao",
            exc.payload.message or "Falha de integracao ao validar provider.",
        )

    @staticmethod
    def _failure(
        *,
        status: str,
        status_label: str,
        message: str,
        provider_id: uuid.UUID,
        provider_slug: str | None,
        checks: list[dict[str, Any]],
        error_code: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "status": status,
            "status_label": status_label,
            "message": message,
            "provider_id": provider_id,
            "provider_slug": provider_slug,
            "checks": checks,
            "error_code": error_code,
        }
