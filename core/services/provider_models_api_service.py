"""
Integracao administrativa remota de modelos por provider.

Qualquer persistencia local neste modulo existe apenas como espelho tecnico legado
e nao pode ser tratada como fonte da verdade.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from models_catalog.models import ProviderModel
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


def _to_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_decimal(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


@dataclass
class ProviderRef:
    id: int | None
    remote_id: UUID | None
    name: str
    slug: str


@dataclass
class ProviderModelReadItem:
    id: int | None
    remote_id: UUID | None
    fastapi_model_id: UUID | None
    provider: ProviderRef
    name: str
    slug: str
    description: str
    context_window: int | None
    input_cost_per_1k: Decimal | None
    output_cost_per_1k: Decimal | None
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None


class ProviderModelsAPIServiceError(Exception):
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


class ProviderModelsAPIService:
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
        if code == "provider_model_not_found":
            return "Modelo remoto nao encontrado na FastAPI."
        if code == "provider_model_slug_conflict":
            return "Ja existe modelo com este slug na FastAPI para o provider informado."
        if code in {"invalid_integration_token", "deactivated_integration_token"}:
            return "Token de integracao FastAPI invalido ou desativado."
        if code == "integration_token_owner_unavailable":
            return "Token de integracao FastAPI sem usuario administrativo ativo."
        if status_code in {401, 403}:
            return "Falha de autenticacao/permissao ao acessar modelos na FastAPI."
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

    def _list_remote_provider_models(self, *, remote_provider_id: UUID) -> ApiResponse:
        return self.client.get(
            f"/api/v1/admin/providers/{remote_provider_id}/models",
            headers=self.client.get_admin_headers(),
            expect_dict=False,
        )

    @staticmethod
    def _provider_ref_from_row(row: dict[str, Any], *, local_id: int | None) -> ProviderRef:
        return ProviderRef(
            id=local_id,
            remote_id=_to_uuid(row.get("id")),
            name=str(row.get("name") or "").strip(),
            slug=str(row.get("slug") or "").strip().lower(),
        )

    def _ensure_local_provider_mirror(self, provider_ref: ProviderRef) -> int | None:
        if provider_ref.remote_id is None:
            return None

        local_provider = Provider.objects.filter(fastapi_provider_id=provider_ref.remote_id).first()
        if local_provider is None:
            local_provider = Provider.objects.filter(
                slug=provider_ref.slug,
                fastapi_provider_id__isnull=True,
            ).first()
        if local_provider is None:
            local_provider = Provider(fastapi_provider_id=provider_ref.remote_id)

        local_provider.name = provider_ref.name
        local_provider.slug = provider_ref.slug
        local_provider.is_active = True
        if not str(local_provider.description or "").strip():
            local_provider.description = ""

        try:
            local_provider.save()
        except IntegrityError:
            return None

        provider_ref.id = local_provider.id
        return local_provider.id

    def _normalize_model_row(
        self,
        row: dict[str, Any],
        *,
        provider_ref: ProviderRef,
    ) -> ProviderModelReadItem | None:
        remote_model_id = _to_uuid(row.get("id"))
        if remote_model_id is None:
            return None

        model_name = str(row.get("model_name") or row.get("name") or "").strip()
        model_slug = str(row.get("model_slug") or row.get("slug") or "").strip().lower()
        if not model_slug:
            return None
        if not model_name:
            model_name = model_slug

        local_model = ProviderModel.objects.filter(fastapi_model_id=remote_model_id).first()
        local_model_id = local_model.id if local_model is not None else None

        return ProviderModelReadItem(
            id=local_model_id,
            remote_id=remote_model_id,
            fastapi_model_id=remote_model_id,
            provider=provider_ref,
            name=model_name,
            slug=model_slug,
            description=str(row.get("description") or "").strip(),
            context_window=_to_int(
                row.get("context_limit")
                if row.get("context_limit") is not None
                else row.get("context_window")
            ),
            input_cost_per_1k=_to_decimal(
                row.get("cost_input_per_1k_tokens")
                if row.get("cost_input_per_1k_tokens") is not None
                else row.get("input_cost_per_1k")
            ),
            output_cost_per_1k=_to_decimal(
                row.get("cost_output_per_1k_tokens")
                if row.get("cost_output_per_1k_tokens") is not None
                else row.get("output_cost_per_1k")
            ),
            is_active=bool(row.get("is_active", False)),
            created_at=_parse_dt(row.get("created_at")),
            updated_at=_parse_dt(row.get("updated_at")),
        )

    @staticmethod
    def _load_local_fallback() -> list[ProviderModelReadItem]:
        items: list[ProviderModelReadItem] = []
        for model in ProviderModel.objects.select_related("provider").all().order_by("provider__name", "name"):
            items.append(
                ProviderModelReadItem(
                    id=model.id,
                    remote_id=model.fastapi_model_id,
                    fastapi_model_id=model.fastapi_model_id,
                    provider=ProviderRef(
                        id=model.provider_id,
                        remote_id=model.provider.fastapi_provider_id,
                        name=str(model.provider.name or "").strip(),
                        slug=str(model.provider.slug or "").strip().lower(),
                    ),
                    name=str(model.name or "").strip(),
                    slug=str(model.slug or "").strip().lower(),
                    description=str(model.description or "").strip(),
                    context_window=model.context_window,
                    input_cost_per_1k=model.input_cost_per_1k,
                    output_cost_per_1k=model.output_cost_per_1k,
                    is_active=bool(model.is_active),
                    created_at=model.created_at,
                    updated_at=model.updated_at,
                )
            )
        return items

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
            return {
                "choices": choices,
                "source": "api",
                "warnings": warnings,
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
        return {
            "choices": [],
            "source": "unavailable",
            "warnings": _dedupe(warnings),
        }

    def get_models_list(self) -> dict[str, Any]:
        warnings: list[str] = []
        providers_result = self._list_remote_providers()
        if not providers_result.is_success or not isinstance(providers_result.data, list):
            code, message = self._extract_error_meta(providers_result)
            warnings.append(
                self._friendly_error(
                    code=code,
                    status_code=providers_result.status_code,
                    fallback_message=message,
                    action="listar providers para catalogo de modelos",
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

        items: list[ProviderModelReadItem] = []
        for provider_row in providers_result.data:
            if not isinstance(provider_row, dict):
                continue
            remote_provider_id = _to_uuid(provider_row.get("id"))
            if remote_provider_id is None:
                continue

            provider_ref = self._provider_ref_from_row(
                provider_row,
                local_id=None,
            )
            local_provider_id = self._ensure_local_provider_mirror(provider_ref)
            provider_ref.id = local_provider_id

            models_result = self._list_remote_provider_models(
                remote_provider_id=remote_provider_id
            )
            if not models_result.is_success or not isinstance(models_result.data, list):
                code, message = self._extract_error_meta(models_result)
                warnings.append(
                    f"Provider {provider_ref.name}: "
                    + self._friendly_error(
                        code=code,
                        status_code=models_result.status_code,
                        fallback_message=message,
                        action="listar modelos do provider",
                    )
                )
                continue

            for model_row in models_result.data:
                if not isinstance(model_row, dict):
                    continue
                item = self._normalize_model_row(model_row, provider_ref=provider_ref)
                if item is None:
                    continue
                items.append(item)

        items.sort(key=lambda item: (item.provider.name.lower(), item.name.lower()))
        if items:
            return {
                "items": items,
                "source": "api",
                "warnings": _dedupe(warnings),
            }

        if warnings:
            return {
                "items": [],
                "source": "unavailable",
                "warnings": _dedupe(warnings),
            }

        return {
            "items": [],
            "source": "api",
            "warnings": [],
        }

    def _upsert_local_model_mirror(self, item: ProviderModelReadItem) -> int | None:
        remote_model_id = item.fastapi_model_id
        provider_ref = item.provider
        if remote_model_id is None or provider_ref.remote_id is None:
            return None

        provider_local_id = provider_ref.id or self._ensure_local_provider_mirror(provider_ref)
        if provider_local_id is None:
            return None

        local_model = ProviderModel.objects.filter(fastapi_model_id=remote_model_id).first()
        if local_model is None:
            local_model = ProviderModel.objects.filter(
                provider_id=provider_local_id,
                slug=item.slug,
            ).first()
        if local_model is None:
            local_model = ProviderModel(
                provider_id=provider_local_id,
                fastapi_model_id=remote_model_id,
            )

        local_model.provider_id = provider_local_id
        local_model.fastapi_model_id = remote_model_id
        local_model.name = item.name
        local_model.slug = item.slug
        local_model.description = item.description
        local_model.context_window = item.context_window
        local_model.input_cost_per_1k = item.input_cost_per_1k or Decimal("0")
        local_model.output_cost_per_1k = item.output_cost_per_1k or Decimal("0")
        local_model.is_active = item.is_active

        try:
            local_model.save()
        except IntegrityError:
            return None

        item.id = local_model.id
        return local_model.id

    def _model_from_remote_response(self, result: ApiResponse) -> ProviderModelReadItem:
        if not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise ProviderModelsAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message or "Resposta invalida da FastAPI para modelo.",
                    action="processar modelo remoto",
                ),
                code=code,
                status_code=result.status_code,
            )

        provider_remote_id = _to_uuid(result.data.get("provider_id"))
        provider_name = ""
        provider_slug = ""
        if provider_remote_id is not None:
            providers_result = self._list_remote_providers()
            if providers_result.is_success and isinstance(providers_result.data, list):
                for row in providers_result.data:
                    if not isinstance(row, dict):
                        continue
                    row_id = _to_uuid(row.get("id"))
                    if row_id != provider_remote_id:
                        continue
                    provider_name = str(row.get("name") or "").strip()
                    provider_slug = str(row.get("slug") or "").strip().lower()
                    break

        provider_ref = ProviderRef(
            id=None,
            remote_id=provider_remote_id,
            name=provider_name or "Provider",
            slug=provider_slug or "",
        )
        self._ensure_local_provider_mirror(provider_ref)

        item = self._normalize_model_row(result.data, provider_ref=provider_ref)
        if item is None:
            raise ProviderModelsAPIServiceError(
                "FastAPI nao retornou ID valido do modelo.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        self._upsert_local_model_mirror(item)
        return item

    def get_model(self, *, remote_model_id: UUID) -> ProviderModelReadItem:
        payload = self.get_models_list()
        for item in payload.get("items", []):
            if not isinstance(item, ProviderModelReadItem):
                continue
            if item.fastapi_model_id == remote_model_id:
                return item
        raise ProviderModelsAPIServiceError(
            "Modelo remoto nao encontrado na FastAPI.",
            code="provider_model_not_found",
            status_code=404,
        )

    def create_model(
        self,
        *,
        remote_provider_id: UUID,
        model_name: str,
        model_slug: str,
        context_window: int | None,
        input_cost_per_1k: Decimal | None,
        output_cost_per_1k: Decimal | None,
        is_active: bool,
    ) -> ProviderModelReadItem:
        payload = {
            "model_name": str(model_name or "").strip(),
            "model_slug": str(model_slug or "").strip().lower(),
            "context_limit": int(context_window or 8192),
            "cost_input_per_1k_tokens": str(input_cost_per_1k or Decimal("0")),
            "cost_output_per_1k_tokens": str(output_cost_per_1k or Decimal("0")),
            "is_active": bool(is_active),
        }
        result = self.client.post(
            f"/api/v1/admin/providers/{remote_provider_id}/models",
            json_body=payload,
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success:
            code, message = self._extract_error_meta(result)
            raise ProviderModelsAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="criar modelo",
                ),
                code=code,
                status_code=result.status_code,
            )
        return self._model_from_remote_response(result)

    def update_model(
        self,
        *,
        remote_model_id: UUID,
        context_window: int | None,
        input_cost_per_1k: Decimal | None,
        output_cost_per_1k: Decimal | None,
        is_active: bool,
    ) -> ProviderModelReadItem:
        payload = {
            "context_limit": int(context_window or 8192),
            "cost_input_per_1k_tokens": str(input_cost_per_1k or Decimal("0")),
            "cost_output_per_1k_tokens": str(output_cost_per_1k or Decimal("0")),
            "is_active": bool(is_active),
        }
        result = self.client.patch(
            f"/api/v1/admin/models/{remote_model_id}",
            json_body=payload,
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success:
            code, message = self._extract_error_meta(result)
            raise ProviderModelsAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="atualizar modelo",
                ),
                code=code,
                status_code=result.status_code,
            )
        return self._model_from_remote_response(result)

    def set_model_status(
        self,
        *,
        remote_model_id: UUID,
        target_active: bool,
    ) -> ProviderModelReadItem:
        action_path = "activate" if target_active else "deactivate"
        result = self.client.patch(
            f"/api/v1/admin/models/{remote_model_id}/{action_path}",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success:
            code, message = self._extract_error_meta(result)
            raise ProviderModelsAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="alterar status do modelo",
                ),
                code=code,
                status_code=result.status_code,
            )
        return self._model_from_remote_response(result)

    def delete_model(self, *, remote_model_id: UUID) -> None:
        result = self.client.delete(
            f"/api/v1/admin/models/{remote_model_id}",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success:
            code, message = self._extract_error_meta(result)
            raise ProviderModelsAPIServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="excluir modelo",
                ),
                code=code,
                status_code=result.status_code,
            )

        local_model = ProviderModel.objects.filter(fastapi_model_id=remote_model_id).first()
        if local_model is None:
            return

        try:
            local_model.delete()
        except (ProtectedError, IntegrityError):
            local_model.is_active = False
            local_model.save(update_fields=["is_active", "updated_at"])

    def get_available_models(self, *, remote_provider_id: UUID) -> dict[str, Any]:
        warnings: list[str] = []

        available_result = self.client.get(
            f"/api/v1/admin/providers/{remote_provider_id}/available-models",
            headers=self.client.get_admin_headers(),
            expect_dict=False,
        )
        if available_result.is_success and isinstance(available_result.data, list):
            items = self._normalize_available_models(
                available_result.data,
                source="api_provider",
            )
            return {
                "items": items,
                "source": "api_provider",
                "warnings": warnings,
                "provider_remote_id": str(remote_provider_id),
            }

        if available_result.status_code == 404:
            catalog_result = self.client.get(
                f"/api/v1/admin/providers/{remote_provider_id}/models",
                headers=self.client.get_admin_headers(),
                expect_dict=False,
            )
            if catalog_result.is_success and isinstance(catalog_result.data, list):
                items = self._normalize_available_models(
                    catalog_result.data,
                    source="api_catalog",
                )
                for item in items:
                    item["is_registered"] = True
                return {
                    "items": items,
                    "source": "api_catalog",
                    "warnings": warnings,
                    "provider_remote_id": str(remote_provider_id),
                }

            code, message = self._extract_error_meta(catalog_result)
            warnings.append(
                self._friendly_error(
                    code=code,
                    status_code=catalog_result.status_code,
                    fallback_message=message,
                    action="listar modelos do provider",
                )
            )
            return {
                "items": [],
                "source": "unavailable",
                "warnings": _dedupe(warnings),
                "provider_remote_id": str(remote_provider_id),
            }

        code, message = self._extract_error_meta(available_result)
        warnings.append(
            self._friendly_error(
                code=code,
                status_code=available_result.status_code,
                fallback_message=message,
                action="listar modelos disponiveis",
            )
        )
        return {
            "items": [],
            "source": "unavailable",
            "warnings": _dedupe(warnings),
            "provider_remote_id": str(remote_provider_id),
        }

    @staticmethod
    def _normalize_available_models(
        rows: list[dict[str, Any]],
        *,
        source: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue

            raw_name = (
                row.get("model_name")
                or row.get("name")
                or row.get("label")
                or row.get("id")
            )
            raw_slug = (
                row.get("model_slug")
                or row.get("slug")
                or row.get("id")
                or raw_name
            )

            name = str(raw_name or "").strip()
            slug = str(raw_slug or "").strip().lower()
            if not slug:
                continue
            if not name:
                name = slug
            if slug in seen_keys:
                continue
            seen_keys.add(slug)

            is_registered = row.get("is_registered")
            if isinstance(is_registered, bool):
                registered = is_registered
            else:
                registered = source == "api_catalog"

            items.append(
                {
                    "key": slug,
                    "label": str(row.get("label") or name).strip() or slug,
                    "name": name,
                    "slug": slug,
                    "fastapi_model_id": str(row.get("id") or "").strip() or None,
                    "provider_model_id": str(row.get("provider_model_id") or slug).strip() or slug,
                    "context_window": _to_int(
                        row.get("context_window")
                        or row.get("context_limit")
                        or row.get("max_context_window")
                    ),
                    "input_cost_per_1k": _to_decimal(
                        row.get("input_cost_per_1k")
                        or row.get("cost_input_per_1k_tokens")
                        or row.get("input_cost")
                    ),
                    "output_cost_per_1k": _to_decimal(
                        row.get("output_cost_per_1k")
                        or row.get("cost_output_per_1k_tokens")
                        or row.get("output_cost")
                    ),
                    "description": str(row.get("description") or "").strip(),
                    "supports_vision": row.get("supports_vision"),
                    "supports_reasoning": row.get("supports_reasoning"),
                    "supports_thinking": row.get("supports_thinking"),
                    "raw_payload": row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else None,
                    "is_registered": registered,
                }
            )
        return items
