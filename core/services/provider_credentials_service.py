from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
from uuid import UUID

from .api_client import ApiResponse, FastAPIClient

if TYPE_CHECKING:
    from credentials.models import ProviderCredential


class ProviderCredentialSyncError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass
class ProviderCredentialSyncResult:
    ok: bool
    status: str
    status_label: str
    message: str
    error_code: str | None
    operation: str
    remote_credential_id: UUID | None = None


class ProviderCredentialsService:
    def __init__(self, *, client: FastAPIClient | None = None) -> None:
        self.client = client or FastAPIClient()

    def sync_credential(
        self,
        *,
        credential: ProviderCredential,
        previous_provider_id: int | None = None,
    ) -> ProviderCredentialSyncResult:
        remote_provider_id = credential.provider.fastapi_provider_id
        if remote_provider_id is None:
            raise ProviderCredentialSyncError(
                "Provider sem vinculo com FastAPI. Sincronize o provider antes da credencial.",
                code="provider_not_synced",
            )

        provider_changed = (
            previous_provider_id is not None and int(previous_provider_id) != int(credential.provider_id)
        )
        if provider_changed or credential.fastapi_credential_id is None:
            return self._create_remote_credential(credential=credential, reason="provider_changed" if provider_changed else "missing_remote")

        return self._update_remote_credential(credential=credential, recreate_on_404=True)

    def sync_credential_status(
        self,
        *,
        credential: ProviderCredential,
        target_active: bool,
    ) -> ProviderCredentialSyncResult:
        if credential.fastapi_credential_id is None:
            raise ProviderCredentialSyncError(
                "Credencial sem vinculo remoto. Use a acao 'Sincronizar com API' antes de alterar status.",
                code="credential_not_synced",
            )

        action_path = "activate" if target_active else "deactivate"
        result = self.client.request_json(
            method="PATCH",
            path=f"/api/v1/admin/credentials/{credential.fastapi_credential_id}/{action_path}",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if result.is_success:
            return ProviderCredentialSyncResult(
                ok=True,
                status="synced",
                status_label="Sincronizada",
                message=(
                    "Status da credencial sincronizado com a FastAPI (ativa)."
                    if target_active
                    else "Status da credencial sincronizado com a FastAPI (inativa)."
                ),
                error_code=None,
                operation="status_updated",
                remote_credential_id=credential.fastapi_credential_id,
            )

        code, message = self._extract_error_meta(result)
        if result.status_code == 404:
            raise ProviderCredentialSyncError(
                "Credencial remota nao encontrada na FastAPI. Use 'Sincronizar com API' para recriar o vinculo.",
                code=code or "provider_credential_not_found",
                status_code=result.status_code,
            )

        raise ProviderCredentialSyncError(
            self._friendly_error(
                code=code,
                status_code=result.status_code,
                fallback_message=message,
                action="sincronizar status",
            ),
            code=code,
            status_code=result.status_code,
        )

    def _create_remote_credential(
        self,
        *,
        credential: ProviderCredential,
        reason: str,
    ) -> ProviderCredentialSyncResult:
        remote_provider_id = credential.provider.fastapi_provider_id
        if remote_provider_id is None:
            raise ProviderCredentialSyncError(
                "Provider sem vinculo com FastAPI. Sincronize o provider antes da credencial.",
                code="provider_not_synced",
            )

        payload = self._build_create_payload(credential)
        result = self.client.request_json(
            method="POST",
            path=f"/api/v1/admin/providers/{remote_provider_id}/credentials",
            json_body=payload,
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success or not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise ProviderCredentialSyncError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="criar credencial remota",
                ),
                code=code,
                status_code=result.status_code,
            )

        remote_id = self._parse_uuid(result.data.get("id"))
        if remote_id is None:
            raise ProviderCredentialSyncError(
                "FastAPI nao retornou ID valido da credencial criada.",
                code="fastapi_invalid_response",
            )

        message = "Credencial criada e sincronizada com a FastAPI."
        if reason == "provider_changed":
            message = (
                "Provider da credencial foi alterado; foi criada uma nova credencial remota na FastAPI."
            )
        return ProviderCredentialSyncResult(
            ok=True,
            status="synced",
            status_label="Sincronizada",
            message=message,
            error_code=None,
            operation="created",
            remote_credential_id=remote_id,
        )

    def _update_remote_credential(
        self,
        *,
        credential: ProviderCredential,
        recreate_on_404: bool,
    ) -> ProviderCredentialSyncResult:
        if credential.fastapi_credential_id is None:
            return self._create_remote_credential(credential=credential, reason="missing_remote")

        payload = self._build_update_payload(credential)
        result = self.client.request_json(
            method="PATCH",
            path=f"/api/v1/admin/credentials/{credential.fastapi_credential_id}",
            json_body=payload,
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if result.is_success:
            return ProviderCredentialSyncResult(
                ok=True,
                status="synced",
                status_label="Sincronizada",
                message="Credencial atualizada e sincronizada com a FastAPI.",
                error_code=None,
                operation="updated",
                remote_credential_id=credential.fastapi_credential_id,
            )

        code, message = self._extract_error_meta(result)
        if result.status_code == 404 and recreate_on_404:
            recreate_result = self._create_remote_credential(credential=credential, reason="missing_remote")
            recreate_result.message = (
                "Credencial remota nao existia mais; o vinculo foi recriado na FastAPI."
            )
            return recreate_result

        raise ProviderCredentialSyncError(
            self._friendly_error(
                code=code,
                status_code=result.status_code,
                fallback_message=message,
                action="atualizar credencial remota",
            ),
            code=code,
            status_code=result.status_code,
        )

    @staticmethod
    def _build_create_payload(credential: ProviderCredential) -> dict[str, Any]:
        return {
            "credential_name": str(credential.name or "").strip(),
            "api_key": str(credential.api_key or "").strip(),
            "config_json": credential.config_json or {},
            "is_active": bool(credential.is_active),
        }

    @staticmethod
    def _build_update_payload(credential: ProviderCredential) -> dict[str, Any]:
        return {
            "credential_name": str(credential.name or "").strip(),
            "api_key": str(credential.api_key or "").strip(),
            "config_json": credential.config_json or {},
            "is_active": bool(credential.is_active),
        }

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
    def _extract_error_meta(result: ApiResponse) -> tuple[str | None, str]:
        code: str | None = None
        message = str(result.error or "").strip()
        if isinstance(result.data, dict):
            error_payload = result.data.get("error")
            if isinstance(error_payload, dict):
                code_value = str(error_payload.get("code") or "").strip()
                if code_value:
                    code = code_value
                payload_message = str(error_payload.get("message") or "").strip()
                if payload_message:
                    message = payload_message
        return code, message

    def _friendly_error(
        self,
        *,
        code: str | None,
        status_code: int | None,
        fallback_message: str,
        action: str,
    ) -> str:
        if code == "provider_not_found":
            return "Provider remoto nao encontrado na FastAPI para esta credencial."
        if code == "provider_not_synced":
            return "Provider local sem vinculo remoto com a FastAPI."
        if code == "provider_credential_name_conflict":
            return "Ja existe uma credencial com este nome na FastAPI para o provider informado."
        if code == "credential_api_key_required":
            return "A FastAPI rejeitou a operacao porque a API key esta vazia."
        if code in {"invalid_integration_token", "deactivated_integration_token"}:
            return "Token de integracao FastAPI invalido ou desativado."
        if code == "integration_token_owner_unavailable":
            return "Token de integracao FastAPI sem usuario administrativo ativo."
        if status_code in {401, 403}:
            return "Falha de autenticacao/permissao ao sincronizar com a FastAPI."
        if status_code == 404:
            return "Recurso remoto nao encontrado na FastAPI durante sincronizacao."
        if status_code is None:
            return fallback_message or "Falha de comunicacao com a FastAPI."
        return fallback_message or f"Falha ao {action} na FastAPI (HTTP {status_code})."
