"""
Integracao administrativa remota de providers.

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

from providers.models import Provider

from .api_client import ApiResponse, FastAPIClient


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
class ProviderReadItem:
    id: int | None
    remote_id: UUID | None
    fastapi_provider_id: UUID | None
    name: str
    slug: str
    description: str
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None
    connectivity_result: dict[str, Any] | None = None


class ProvidersAPIServiceError(Exception):
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


class ProvidersAPIService:
    def __init__(self, *, client: FastAPIClient | None = None) -> None:
        self.client = client or FastAPIClient()

    @staticmethod
    def _build_payload(
        *,
        name: str,
        slug: str,
        description: str,
        is_active: bool,
    ) -> dict[str, Any]:
        return {
            "name": str(name or "").strip(),
            "slug": str(slug or "").strip().lower(),
            "description": str(description or "").strip() or None,
            "is_active": bool(is_active),
        }

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
        if code == "provider_slug_conflict":
            return "Ja existe um provider com este slug na FastAPI."
        if code == "provider_not_found":
            return "Provider remoto nao encontrado na FastAPI."
        if code in {"invalid_integration_token", "deactivated_integration_token"}:
            return "Token de integracao FastAPI invalido ou desativado."
        if code == "integration_token_owner_unavailable":
            return "Token de integracao FastAPI sem usuario administrativo ativo."
        if status_code in {401, 403}:
            return "Falha de autenticacao/permissao ao acessar providers na FastAPI."
        if status_code == 404:
            return "Provider remoto nao encontrado na FastAPI."
        if status_code is None:
            return fallback_message or "Falha de comunicacao com a FastAPI."
        return fallback_message or f"Falha ao {action} na FastAPI (HTTP {status_code})."

    def _normalize_remote_row(
        self,
        row: dict[str, Any],
        *,
        local_map: dict[str, Provider] | None = None,
    ) -> ProviderReadItem | None:
        remote_id = _to_uuid(row.get("id"))
        if remote_id is None:
            return None

        local_provider = local_map.get(str(remote_id)) if local_map is not None else None
        return ProviderReadItem(
            id=local_provider.id if local_provider is not None else None,
            remote_id=remote_id,
            fastapi_provider_id=remote_id,
            name=str(row.get("name") or "").strip(),
            slug=str(row.get("slug") or "").strip().lower(),
            description=str(row.get("description") or "").strip(),
            is_active=bool(row.get("is_active", False)),
            created_at=_parse_dt(row.get("created_at")),
            updated_at=_parse_dt(row.get("updated_at")),
        )

    def _build_local_map(self, *, remote_ids: list[UUID]) -> dict[str, Provider]:
        local_map: dict[str, Provider] = {}
        if not remote_ids:
            return local_map

        local_candidates = Provider.objects.filter(fastapi_provider_id__in=remote_ids).only(
            "id",
            "fastapi_provider_id",
        )
        for local_provider in local_candidates:
            if local_provider.fastapi_provider_id is None:
                continue
            local_map[str(local_provider.fastapi_provider_id)] = local_provider
        return local_map

    def _normalize_remote_items(self, result: ApiResponse) -> list[ProviderReadItem]:
        if not isinstance(result.data, list):
            return []

        remote_rows = [item for item in result.data if isinstance(item, dict)]
        remote_ids = [_to_uuid(row.get("id")) for row in remote_rows]
        remote_ids = [item for item in remote_ids if item is not None]
        local_map = self._build_local_map(remote_ids=remote_ids)

        items: list[ProviderReadItem] = []
        for row in remote_rows:
            item = self._normalize_remote_row(row, local_map=local_map)
            if item is None:
                continue
            items.append(item)
        return items

    @staticmethod
    def _load_local_fallback() -> list[ProviderReadItem]:
        fallback_items: list[ProviderReadItem] = []
        for provider in Provider.objects.all().order_by("name"):
            fallback_items.append(
                ProviderReadItem(
                    id=provider.id,
                    remote_id=provider.fastapi_provider_id,
                    fastapi_provider_id=provider.fastapi_provider_id,
                    name=str(provider.name or "").strip(),
                    slug=str(provider.slug or "").strip().lower(),
                    description=str(provider.description or "").strip(),
                    is_active=bool(provider.is_active),
                    created_at=provider.created_at,
                    updated_at=provider.updated_at,
                )
            )
        return fallback_items

    @staticmethod
    def _upsert_local_mirror(item: ProviderReadItem) -> int | None:
        remote_id = item.fastapi_provider_id
        if remote_id is None:
            return None

        local_provider = Provider.objects.filter(fastapi_provider_id=remote_id).first()
        if local_provider is None:
            local_provider = Provider(fastapi_provider_id=remote_id)

        local_provider.name = str(item.name or "").strip()
        local_provider.slug = str(item.slug or "").strip().lower()
        local_provider.description = str(item.description or "").strip()
        local_provider.is_active = bool(item.is_active)

        try:
            local_provider.save()
        except IntegrityError:
            return None

        item.id = local_provider.id
        return local_provider.id

    def _parse_provider_result(self, result: ApiResponse) -> ProviderReadItem:
        if not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise ProvidersAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message or "Resposta invalida ao processar provider remoto.",
                    action="processar provider",
                ),
                code=code,
                status_code=result.status_code,
            )

        item = self._normalize_remote_row(result.data)
        if item is None:
            raise ProvidersAPIServiceError(
                "FastAPI nao retornou ID valido do provider.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        self._upsert_local_mirror(item)
        return item

    def get_providers_list(self) -> dict[str, Any]:
        warnings: list[str] = []
        result = self.client.get(
            "/api/v1/admin/providers",
            headers=self.client.get_admin_headers(),
            expect_dict=False,
        )

        if result.is_success and isinstance(result.data, list):
            remote_items = self._normalize_remote_items(result)
            unmapped_count = len([item for item in remote_items if item.id is None])
            if unmapped_count:
                warnings.append(
                    f"{unmapped_count} provider(s) existem na API sem vinculo local no Django (leitura mantida via API)."
                )
            return {
                "items": remote_items,
                "source": "api",
                "warnings": _dedupe(warnings),
            }

        if result.is_success:
            warnings.append(
                "Resposta inesperada da FastAPI ao listar providers. Fallback local temporario ativado."
            )
            warnings.append(
                "Fallback local temporario ativado para manter a tela funcional; a fonte oficial permanece a API."
            )
            return {
                "items": self._load_local_fallback(),
                "source": "fallback_local",
                "warnings": _dedupe(warnings),
            }

        code, message = self._extract_error_meta(result)
        warnings.append(
            self._friendly_error(
                code=code,
                status_code=result.status_code,
                fallback_message=message,
                action="listar providers",
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

    def get_provider(self, *, remote_provider_id: UUID) -> ProviderReadItem:
        result = self.client.get(
            "/api/v1/admin/providers",
            headers=self.client.get_admin_headers(),
            expect_dict=False,
        )
        if not result.is_success:
            code, message = self._extract_error_meta(result)
            raise ProvidersAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="consultar provider",
                ),
                code=code,
                status_code=result.status_code,
            )
        if not isinstance(result.data, list):
            raise ProvidersAPIServiceError(
                "Resposta invalida da FastAPI ao consultar provider.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )

        remote_ids = [remote_provider_id]
        local_map = self._build_local_map(remote_ids=remote_ids)
        for row in result.data:
            if not isinstance(row, dict):
                continue
            item_id = _to_uuid(row.get("id"))
            if item_id != remote_provider_id:
                continue
            item = self._normalize_remote_row(row, local_map=local_map)
            if item is None:
                break
            self._upsert_local_mirror(item)
            return item

        raise ProvidersAPIServiceError(
            "Provider remoto nao encontrado na FastAPI.",
            code="provider_not_found",
            status_code=404,
        )

    def create_provider(
        self,
        *,
        name: str,
        slug: str,
        description: str,
        is_active: bool,
    ) -> ProviderReadItem:
        payload = self._build_payload(
            name=name,
            slug=slug,
            description=description,
            is_active=is_active,
        )
        result = self.client.post(
            "/api/v1/admin/providers",
            json_body=payload,
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success:
            code, message = self._extract_error_meta(result)
            raise ProvidersAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="criar provider",
                ),
                code=code,
                status_code=result.status_code,
            )
        return self._parse_provider_result(result)

    def update_provider(
        self,
        *,
        remote_provider_id: UUID,
        name: str,
        slug: str,
        description: str,
        is_active: bool,
    ) -> ProviderReadItem:
        payload = self._build_payload(
            name=name,
            slug=slug,
            description=description,
            is_active=is_active,
        )
        result = self.client.patch(
            f"/api/v1/admin/providers/{remote_provider_id}",
            json_body=payload,
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success:
            code, message = self._extract_error_meta(result)
            raise ProvidersAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="atualizar provider",
                ),
                code=code,
                status_code=result.status_code,
            )
        return self._parse_provider_result(result)

    def set_provider_status(
        self,
        *,
        remote_provider_id: UUID,
        target_active: bool,
    ) -> ProviderReadItem:
        action_path = "activate" if target_active else "deactivate"
        result = self.client.patch(
            f"/api/v1/admin/providers/{remote_provider_id}/{action_path}",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success:
            code, message = self._extract_error_meta(result)
            raise ProvidersAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="alterar status do provider",
                ),
                code=code,
                status_code=result.status_code,
            )
        return self._parse_provider_result(result)

    def test_provider_connectivity(self, *, remote_provider_id: UUID) -> dict[str, Any]:
        result = self.client.post(
            f"/api/v1/admin/providers/{remote_provider_id}/connectivity-test",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )

        if result.is_success and isinstance(result.data, dict):
            return {
                "ok": bool(result.data.get("ok")),
                "status": str(result.data.get("status") or "unknown"),
                "status_label": str(result.data.get("status_label") or "Status desconhecido"),
                "message": str(result.data.get("message") or ""),
                "checks": result.data.get("checks", []),
                "error_code": str(result.data.get("error_code") or "") or None,
            }

        code, message = self._extract_error_meta(result)
        if result.status_code == 404:
            return {
                "ok": False,
                "status": "provider_remote_not_found",
                "status_label": "Provider remoto inexistente",
                "message": message or "Provider remoto nao encontrado na FastAPI.",
                "checks": [],
                "error_code": code or "provider_not_found",
            }
        if result.status_code in {401, 403}:
            return {
                "ok": False,
                "status": "admin_auth_error",
                "status_label": "Falha de autenticacao",
                "message": message or "Falha de autenticacao administrativa com a FastAPI.",
                "checks": [],
                "error_code": code or "admin_auth_error",
            }
        if result.status_code is None:
            return {
                "ok": False,
                "status": "integration_error",
                "status_label": "Falha de integracao",
                "message": message or "Falha de integracao ao chamar FastAPI.",
                "checks": [],
                "error_code": code or "integration_error",
            }

        return {
            "ok": False,
            "status": "integration_error",
            "status_label": "Falha de integracao",
            "message": message or f"FastAPI retornou HTTP {result.status_code} no teste de conectividade.",
            "checks": [],
            "error_code": code or "integration_error",
        }
