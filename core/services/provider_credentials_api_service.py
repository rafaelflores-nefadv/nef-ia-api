"""
Integracao administrativa remota de credenciais.

Qualquer persistencia local neste modulo existe apenas como espelho tecnico legado
e nao pode ser tratada como fonte da verdade.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import IntegrityError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from credentials.models import ProviderCredential
from providers.models import Provider

from .api_client import ApiResponse, FastAPIClient

LEGACY_REMOTE_SECRET_PLACEHOLDER = "__REMOTE_MANAGED__"


def _dedupe(values: list[str]) -> list[str]:
    unique: list[str] = []
    for item in values:
        normalized = str(item or "").strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return timezone.localtime(value)
        return timezone.make_aware(value, timezone.get_current_timezone())
    if isinstance(value, str):
        parsed = parse_datetime(value)
        if parsed is None:
            return None
        if timezone.is_aware(parsed):
            return timezone.localtime(parsed)
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return None


def _to_uuid(value: Any) -> UUID | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


@dataclass
class ProviderRef:
    id: int | None
    remote_id: UUID | None
    name: str
    slug: str
    is_active: bool


@dataclass
class ProviderCredentialReadItem:
    id: int | None
    remote_id: UUID | None
    fastapi_credential_id: UUID | None
    provider: ProviderRef
    name: str
    config_json: dict[str, Any]
    is_active: bool
    secret_masked: str
    created_at: datetime | None
    updated_at: datetime | None
    sync_result: dict[str, Any] | None = None
    connectivity_result: dict[str, Any] | None = None

    @property
    def masked_api_key(self) -> str:
        masked = str(self.secret_masked or "").strip()
        return masked or "********"


class ProviderCredentialsAPIServiceError(Exception):
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


class ProviderCredentialsAPIService:
    def __init__(self, *, client: FastAPIClient | None = None) -> None:
        self.client = client or FastAPIClient()

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
            return "Provider remoto nao encontrado na FastAPI."
        if code == "provider_credential_not_found":
            return "Credencial remota nao encontrada na FastAPI."
        if code == "provider_credential_name_conflict":
            return "Ja existe credencial com este nome na FastAPI para o provider informado."
        if code == "credential_api_key_required":
            return "A FastAPI exige API key para esta operacao."
        if code in {"invalid_integration_token", "deactivated_integration_token"}:
            return "Token de integracao FastAPI invalido ou desativado."
        if code == "integration_token_owner_unavailable":
            return "Token de integracao FastAPI sem usuario administrativo ativo."
        if status_code in {401, 403}:
            return "Falha de autenticacao/permissao ao acessar credenciais na FastAPI."
        if status_code == 404:
            return "Recurso remoto nao encontrado na FastAPI."
        if status_code is None:
            return fallback_message or "Falha de comunicacao com a FastAPI."
        return fallback_message or f"Falha ao {action} na FastAPI (HTTP {status_code})."

    def _list_remote_providers(self) -> ApiResponse:
        return self.client.get(
            "/api/v1/admin/providers",
            headers=self.client.get_admin_headers(),
            expect_dict=False,
        )

    def _list_remote_provider_credentials(self, *, remote_provider_id: UUID) -> ApiResponse:
        return self.client.get(
            f"/api/v1/admin/providers/{remote_provider_id}/credentials",
            headers=self.client.get_admin_headers(),
            expect_dict=False,
        )

    @staticmethod
    def _provider_from_row(row: dict[str, Any]) -> ProviderRef | None:
        remote_id = _to_uuid(row.get("id"))
        if remote_id is None:
            return None
        return ProviderRef(
            id=None,
            remote_id=remote_id,
            name=str(row.get("name") or "").strip(),
            slug=str(row.get("slug") or "").strip().lower(),
            is_active=bool(row.get("is_active", False)),
        )

    def _ensure_local_provider_mirror(self, provider_ref: ProviderRef) -> int | None:
        if provider_ref.remote_id is None:
            return None

        local_provider = Provider.objects.filter(
            fastapi_provider_id=provider_ref.remote_id
        ).first()
        if local_provider is None:
            local_provider = Provider.objects.filter(
                slug=provider_ref.slug,
                fastapi_provider_id__isnull=True,
            ).first()
        if local_provider is None:
            local_provider = Provider(fastapi_provider_id=provider_ref.remote_id)

        local_provider.name = provider_ref.name
        local_provider.slug = provider_ref.slug
        local_provider.is_active = provider_ref.is_active
        if not str(local_provider.description or "").strip():
            local_provider.description = ""

        try:
            local_provider.save()
        except IntegrityError:
            return None

        provider_ref.id = local_provider.id
        return local_provider.id

    def _normalize_credential_row(
        self,
        row: dict[str, Any],
        *,
        provider_ref: ProviderRef,
    ) -> ProviderCredentialReadItem | None:
        remote_credential_id = _to_uuid(row.get("id"))
        if remote_credential_id is None:
            return None

        credential_name = str(
            row.get("credential_name") or row.get("name") or ""
        ).strip()
        if not credential_name:
            return None

        config_payload = row.get("config_json")
        if not isinstance(config_payload, dict):
            config_payload = {}

        local_credential = ProviderCredential.objects.filter(
            fastapi_credential_id=remote_credential_id
        ).first()
        local_id = local_credential.id if local_credential is not None else None

        return ProviderCredentialReadItem(
            id=local_id,
            remote_id=remote_credential_id,
            fastapi_credential_id=remote_credential_id,
            provider=provider_ref,
            name=credential_name,
            config_json=config_payload,
            is_active=bool(row.get("is_active", False)),
            secret_masked=str(row.get("secret_masked") or "").strip() or "********",
            created_at=_parse_dt(row.get("created_at")),
            updated_at=_parse_dt(row.get("updated_at")),
        )

    @staticmethod
    def _load_local_fallback() -> list[ProviderCredentialReadItem]:
        fallback_items: list[ProviderCredentialReadItem] = []
        queryset = ProviderCredential.objects.select_related("provider").all().order_by(
            "provider__name", "name"
        )
        for credential in queryset:
            fallback_items.append(
                ProviderCredentialReadItem(
                    id=credential.id,
                    remote_id=credential.fastapi_credential_id,
                    fastapi_credential_id=credential.fastapi_credential_id,
                    provider=ProviderRef(
                        id=credential.provider_id,
                        remote_id=credential.provider.fastapi_provider_id,
                        name=str(credential.provider.name or "").strip(),
                        slug=str(credential.provider.slug or "").strip().lower(),
                        is_active=bool(credential.provider.is_active),
                    ),
                    name=str(credential.name or "").strip(),
                    config_json=credential.config_json or {},
                    is_active=bool(credential.is_active),
                    secret_masked=credential.masked_api_key,
                    created_at=credential.created_at,
                    updated_at=credential.updated_at,
                )
            )
        return fallback_items

    def _upsert_local_credential_mirror(self, item: ProviderCredentialReadItem) -> int | None:
        if item.fastapi_credential_id is None or item.provider.id is None:
            return None

        local_credential = ProviderCredential.objects.filter(
            fastapi_credential_id=item.fastapi_credential_id
        ).first()
        if local_credential is None:
            local_credential = ProviderCredential.objects.filter(
                provider_id=item.provider.id,
                name=item.name,
            ).first()
        if local_credential is None:
            local_credential = ProviderCredential(
                provider_id=item.provider.id,
                fastapi_credential_id=item.fastapi_credential_id,
            )

        local_credential.provider_id = item.provider.id
        local_credential.fastapi_credential_id = item.fastapi_credential_id
        local_credential.name = item.name
        local_credential.config_json = item.config_json or {}
        local_credential.is_active = bool(item.is_active)
        # Mantem apenas marcador tecnico local para legado; segredo oficial permanece remoto.
        local_credential.api_key = LEGACY_REMOTE_SECRET_PLACEHOLDER

        try:
            local_credential.save()
        except IntegrityError:
            return None

        item.id = local_credential.id
        return local_credential.id

    def _build_credential_item_from_response(
        self,
        result: ApiResponse,
        *,
        remote_provider_id: UUID | None = None,
    ) -> ProviderCredentialReadItem:
        if not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise ProviderCredentialsAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message or "Resposta invalida da FastAPI para credencial.",
                    action="processar credencial remota",
                ),
                code=code,
                status_code=result.status_code,
            )

        provider_remote_id = remote_provider_id or _to_uuid(result.data.get("provider_id"))
        if provider_remote_id is None:
            raise ProviderCredentialsAPIServiceError(
                "FastAPI nao retornou provider valido para a credencial.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )

        provider_ref = self._resolve_provider_ref(remote_provider_id=provider_remote_id)
        item = self._normalize_credential_row(result.data, provider_ref=provider_ref)
        if item is None:
            raise ProviderCredentialsAPIServiceError(
                "FastAPI nao retornou ID valido da credencial.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )

        self._upsert_local_credential_mirror(item)
        return item

    def _resolve_provider_ref(self, *, remote_provider_id: UUID) -> ProviderRef:
        providers_result = self._list_remote_providers()
        if providers_result.is_success and isinstance(providers_result.data, list):
            for row in providers_result.data:
                if not isinstance(row, dict):
                    continue
                row_id = _to_uuid(row.get("id"))
                if row_id != remote_provider_id:
                    continue
                provider_ref = self._provider_from_row(row)
                if provider_ref is None:
                    break
                self._ensure_local_provider_mirror(provider_ref)
                return provider_ref

        local_provider = Provider.objects.filter(fastapi_provider_id=remote_provider_id).first()
        if local_provider is not None:
            return ProviderRef(
                id=local_provider.id,
                remote_id=local_provider.fastapi_provider_id,
                name=str(local_provider.name or "").strip(),
                slug=str(local_provider.slug or "").strip().lower(),
                is_active=bool(local_provider.is_active),
            )

        raise ProviderCredentialsAPIServiceError(
            "Provider remoto nao encontrado na FastAPI.",
            code="provider_not_found",
            status_code=404,
        )

    def get_provider_choices(self) -> dict[str, Any]:
        result = self._list_remote_providers()
        warnings: list[str] = []
        choices: list[tuple[str, str]] = []

        if result.is_success and isinstance(result.data, list):
            for row in result.data:
                if not isinstance(row, dict):
                    continue
                remote_id = _to_uuid(row.get("id"))
                if remote_id is None:
                    continue
                name = str(row.get("name") or "").strip()
                slug = str(row.get("slug") or "").strip().lower()
                label = name or slug or str(remote_id)
                choices.append((str(remote_id), label))
            choices = sorted(choices, key=lambda item: item[1].lower())
            return {"choices": choices, "source": "api", "warnings": warnings}

        code, message = self._extract_error_meta(result)
        warnings.append(
            self._friendly_error(
                code=code,
                status_code=result.status_code,
                fallback_message=message,
                action="listar providers",
            )
        )
        for provider in Provider.objects.order_by("name"):
            if provider.fastapi_provider_id is None:
                continue
            choices.append((str(provider.fastapi_provider_id), provider.name))
        if choices:
            warnings.append(
                "Lista de providers em fallback local temporario; a fonte oficial permanece a API."
            )
            return {
                "choices": choices,
                "source": "fallback_local",
                "warnings": _dedupe(warnings),
            }
        return {"choices": [], "source": "unavailable", "warnings": _dedupe(warnings)}

    def get_credentials_list(self) -> dict[str, Any]:
        warnings: list[str] = []
        providers_result = self._list_remote_providers()
        if not providers_result.is_success or not isinstance(providers_result.data, list):
            code, message = self._extract_error_meta(providers_result)
            warnings.append(
                self._friendly_error(
                    code=code,
                    status_code=providers_result.status_code,
                    fallback_message=message,
                    action="listar providers para catalogo de credenciais",
                )
            )
            warnings.append(
                "Fallback local temporario ativado para manter a tela funcional; a fonte oficial permanece a API."
            )
            return {
                "items": self._load_local_fallback(),
                "source": "fallback_local",
                "warnings": _dedupe(warnings),
            }

        items: list[ProviderCredentialReadItem] = []
        for provider_row in providers_result.data:
            if not isinstance(provider_row, dict):
                continue
            provider_ref = self._provider_from_row(provider_row)
            if provider_ref is None or provider_ref.remote_id is None:
                continue
            self._ensure_local_provider_mirror(provider_ref)

            credentials_result = self._list_remote_provider_credentials(
                remote_provider_id=provider_ref.remote_id
            )
            if not credentials_result.is_success or not isinstance(
                credentials_result.data, list
            ):
                code, message = self._extract_error_meta(credentials_result)
                warnings.append(
                    f"Provider {provider_ref.name}: "
                    + self._friendly_error(
                        code=code,
                        status_code=credentials_result.status_code,
                        fallback_message=message,
                        action="listar credenciais do provider",
                    )
                )
                continue

            for credential_row in credentials_result.data:
                if not isinstance(credential_row, dict):
                    continue
                item = self._normalize_credential_row(
                    credential_row,
                    provider_ref=provider_ref,
                )
                if item is None:
                    continue
                self._upsert_local_credential_mirror(item)
                items.append(item)

        items.sort(key=lambda item: (item.provider.name.lower(), item.name.lower()))
        if items:
            return {"items": items, "source": "api", "warnings": _dedupe(warnings)}
        if warnings:
            return {"items": [], "source": "unavailable", "warnings": _dedupe(warnings)}
        return {"items": [], "source": "api", "warnings": []}

    def get_credential(self, *, remote_credential_id: UUID) -> ProviderCredentialReadItem:
        payload = self.get_credentials_list()
        for item in payload.get("items", []):
            if not isinstance(item, ProviderCredentialReadItem):
                continue
            if item.fastapi_credential_id == remote_credential_id:
                return item
        raise ProviderCredentialsAPIServiceError(
            "Credencial remota nao encontrada na FastAPI.",
            code="provider_credential_not_found",
            status_code=404,
        )

    def create_credential(
        self,
        *,
        remote_provider_id: UUID,
        credential_name: str,
        api_key: str,
        config_json: dict[str, Any] | None,
        is_active: bool,
    ) -> ProviderCredentialReadItem:
        payload = {
            "credential_name": str(credential_name or "").strip(),
            "api_key": str(api_key or "").strip(),
            "config_json": config_json or {},
            "is_active": bool(is_active),
        }
        result = self.client.post(
            f"/api/v1/admin/providers/{remote_provider_id}/credentials",
            json_body=payload,
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success:
            code, message = self._extract_error_meta(result)
            raise ProviderCredentialsAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="criar credencial",
                ),
                code=code,
                status_code=result.status_code,
            )
        return self._build_credential_item_from_response(
            result,
            remote_provider_id=remote_provider_id,
        )

    def update_credential(
        self,
        *,
        remote_credential_id: UUID,
        credential_name: str,
        api_key: str | None,
        config_json: dict[str, Any] | None,
        is_active: bool,
    ) -> ProviderCredentialReadItem:
        payload: dict[str, Any] = {
            "credential_name": str(credential_name or "").strip(),
            "is_active": bool(is_active),
        }
        if config_json is not None:
            payload["config_json"] = config_json
        normalized_api_key = str(api_key or "").strip()
        if normalized_api_key:
            payload["api_key"] = normalized_api_key

        result = self.client.patch(
            f"/api/v1/admin/credentials/{remote_credential_id}",
            json_body=payload,
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success:
            code, message = self._extract_error_meta(result)
            raise ProviderCredentialsAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="atualizar credencial",
                ),
                code=code,
                status_code=result.status_code,
            )
        return self._build_credential_item_from_response(result)

    def set_credential_status(
        self,
        *,
        remote_credential_id: UUID,
        target_active: bool,
    ) -> ProviderCredentialReadItem:
        action_path = "activate" if target_active else "deactivate"
        result = self.client.patch(
            f"/api/v1/admin/credentials/{remote_credential_id}/{action_path}",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success:
            code, message = self._extract_error_meta(result)
            raise ProviderCredentialsAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="alterar status da credencial",
                ),
                code=code,
                status_code=result.status_code,
            )
        return self._build_credential_item_from_response(result)
