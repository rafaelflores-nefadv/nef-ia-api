from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from models_catalog.catalog import get_known_models
from providers.models import Provider

from .api_client import ApiResponse, FastAPIClient

logger = logging.getLogger(__name__)


class ProviderModelsServiceError(Exception):
    pass


def _dedupe(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


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


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "sim"}:
            return True
        if normalized in {"0", "false", "no", "nao"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _to_uuid(value: Any) -> UUID | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


class ProviderModelsService:
    def __init__(self):
        self.client = FastAPIClient()
        self.admin_token = self.client.admin_token

    def _auth_headers(self) -> dict[str, str] | None:
        return self.client.get_admin_headers()

    def _fallback_items(self, provider: Provider) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for model in get_known_models(provider.slug):
            items.append(
                {
                    "key": model.key,
                    "label": model.label,
                    "name": model.name,
                    "slug": model.slug,
                    "fastapi_model_id": None,
                    "provider_model_id": model.key,
                    "context_window": model.context_window,
                    "input_cost_per_1k": model.input_cost_per_1k,
                    "output_cost_per_1k": model.output_cost_per_1k,
                    "description": model.description,
                    "is_registered": False,
                }
            )
        return items

    def _extract_error_meta(self, result: ApiResponse) -> tuple[str | None, str]:
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

    def _is_integration_failure(self, result: ApiResponse) -> bool:
        if result.status_code is None:
            return True
        return result.status_code >= 500

    def _format_provider_discovery_error(
        self,
        *,
        provider: Provider,
        result: ApiResponse,
    ) -> str:
        code, message = self._extract_error_meta(result)
        if code == "provider_credential_not_found":
            return "Provider remoto sem credencial ativa na FastAPI."
        if code == "provider_inactive":
            return "Provider remoto esta inativo na FastAPI."
        if code == "provider_discovery_not_supported":
            return (
                "Descoberta dinamica ainda nao suportada para este provider. "
                "No momento, o fluxo dinamico esta disponivel para OpenAI, Anthropic/Claude e Gemini."
            )
        if code == "provider_not_found":
            return "Provider remoto nao encontrado na FastAPI para o vinculo informado."
        if code in {"invalid_integration_token", "deactivated_integration_token"}:
            return "Token de integracao FastAPI invalido ou desativado."
        if code == "integration_token_owner_unavailable":
            return "Token de integracao FastAPI sem usuario administrativo ativo."
        if result.status_code in {401, 403}:
            if self.admin_token:
                return "Token administrativo FastAPI invalido ou sem permissao."
            return "Token administrativo FastAPI nao configurado."
        return message or f"Falha ao consultar modelos na FastAPI (HTTP {result.status_code})."

    def _normalize_model_item(
        self,
        row: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any] | None:
        raw_name = row.get("model_name") or row.get("name") or row.get("label") or row.get("id")
        raw_slug = row.get("model_slug") or row.get("slug") or row.get("id") or raw_name

        name = str(raw_name or "").strip()
        slug = str(raw_slug or "").strip().lower()
        if not name and slug:
            name = slug
        if not slug:
            return None

        label = str(row.get("label") or name or slug).strip() or slug
        context_window = _to_int(
            row.get("context_window")
            or row.get("context_limit")
            or row.get("max_context_window")
        )
        input_cost = _to_decimal(
            row.get("input_cost_per_1k")
            or row.get("cost_input_per_1k_tokens")
            or row.get("input_cost")
        )
        output_cost = _to_decimal(
            row.get("output_cost_per_1k")
            or row.get("cost_output_per_1k_tokens")
            or row.get("output_cost")
        )
        description = str(row.get("description") or "").strip()
        supports_vision = _to_bool(row.get("supports_vision"))
        supports_reasoning = _to_bool(row.get("supports_reasoning"))
        supports_thinking = _to_bool(row.get("supports_thinking"))
        raw_payload = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else None

        raw_is_registered = row.get("is_registered")
        if isinstance(raw_is_registered, bool):
            is_registered = raw_is_registered
        elif isinstance(raw_is_registered, str):
            is_registered = raw_is_registered.strip().lower() in {"1", "true", "yes", "sim"}
        elif isinstance(raw_is_registered, (int, float)):
            is_registered = bool(raw_is_registered)
        else:
            is_registered = source == "api_catalog"

        fastapi_model_id = str(row.get("id") or "").strip() or None
        provider_model_id = str(row.get("provider_model_id") or slug).strip() or slug

        return {
            "key": slug,
            "label": label,
            "name": name or slug,
            "slug": slug,
            "fastapi_model_id": fastapi_model_id,
            "provider_model_id": provider_model_id,
            "context_window": context_window,
            "input_cost_per_1k": input_cost,
            "output_cost_per_1k": output_cost,
            "description": description,
            "is_registered": is_registered,
            "supports_vision": supports_vision,
            "supports_reasoning": supports_reasoning,
            "supports_thinking": supports_thinking,
            "raw_payload": raw_payload,
        }

    def _parse_model_payload(self, result: ApiResponse, *, source: str) -> list[dict[str, Any]]:
        raw_items: list[dict[str, Any]] = []
        if isinstance(result.data, list):
            raw_items = [item for item in result.data if isinstance(item, dict)]
        elif isinstance(result.data, dict):
            candidate_items = result.data.get("items")
            if isinstance(candidate_items, list):
                raw_items = [item for item in candidate_items if isinstance(item, dict)]

        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in raw_items:
            item = self._normalize_model_item(row, source=source)
            if item is None:
                continue
            slug = str(item.get("slug") or "")
            if not slug or slug in seen:
                continue
            seen.add(slug)
            normalized.append(item)
        return normalized

    @staticmethod
    def _normalize_lookup_key(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        if raw.startswith("models/"):
            raw = raw[len("models/") :]
        raw = (
            raw.replace("_", "-")
            .replace(".", "-")
            .replace(" ", "-")
            .replace("/", "-")
        )
        parts = [part for part in raw.split("-") if part]
        return "-".join(parts)

    @staticmethod
    def _is_missing_value(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        return False

    def _with_known_model_metadata_fallback(
        self,
        *,
        provider: Provider,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        known_models = list(get_known_models(provider.slug))
        if not known_models:
            return items

        known_index: dict[str, Any] = {}
        for known in known_models:
            for candidate in (known.slug, known.key, known.name, known.label):
                normalized_candidate = self._normalize_lookup_key(candidate)
                if normalized_candidate:
                    known_index[normalized_candidate] = known

        enriched: list[dict[str, Any]] = []
        for item in items:
            lookup_candidates = (
                item.get("slug"),
                item.get("key"),
                item.get("provider_model_id"),
                item.get("name"),
                item.get("label"),
            )
            known = None
            for candidate in lookup_candidates:
                normalized_candidate = self._normalize_lookup_key(candidate)
                if not normalized_candidate:
                    continue
                known = known_index.get(normalized_candidate)
                if known is not None:
                    break

            if known is None:
                enriched.append(item)
                continue

            normalized_item = dict(item)
            if (
                self._is_missing_value(normalized_item.get("context_window"))
                and known.context_window is not None
            ):
                normalized_item["context_window"] = known.context_window
            if (
                self._is_missing_value(normalized_item.get("input_cost_per_1k"))
                and known.input_cost_per_1k is not None
            ):
                normalized_item["input_cost_per_1k"] = known.input_cost_per_1k
            if (
                self._is_missing_value(normalized_item.get("output_cost_per_1k"))
                and known.output_cost_per_1k is not None
            ):
                normalized_item["output_cost_per_1k"] = known.output_cost_per_1k
            if (
                self._is_missing_value(normalized_item.get("description"))
                and str(known.description or "").strip()
            ):
                normalized_item["description"] = known.description

            enriched.append(normalized_item)
        return enriched

    def sync_provider(self, *, provider: Provider) -> UUID:
        payload = {
            "name": str(provider.name or "").strip(),
            "slug": str(provider.slug or "").strip().lower(),
            "description": str(provider.description or "").strip() or None,
            "is_active": bool(provider.is_active),
        }

        remote_id = provider.fastapi_provider_id
        if remote_id is not None:
            result = self.client.request_json(
                method="PATCH",
                path=f"/api/v1/admin/providers/{remote_id}",
                json_body=payload,
                headers=self._auth_headers(),
                expect_dict=True,
            )
            if result.is_success and isinstance(result.data, dict):
                parsed_remote_id = _to_uuid(result.data.get("id"))
                if parsed_remote_id is not None:
                    return parsed_remote_id
                return remote_id

            if result.status_code != 404:
                code, message = self._extract_error_meta(result)
                raise ProviderModelsServiceError(
                    message
                    or f"Falha ao atualizar provider remoto na FastAPI (HTTP {result.status_code}, code={code})."
                )

        create_result = self.client.request_json(
            method="POST",
            path="/api/v1/admin/providers",
            json_body=payload,
            headers=self._auth_headers(),
            expect_dict=True,
        )
        create_code, create_message = self._extract_error_meta(create_result)
        if create_result.status_code == 409 and create_code == "provider_slug_conflict":
            recovered_id = self._recover_provider_id_by_slug_conflict(slug=payload["slug"])
            if recovered_id is not None:
                update_result = self.client.request_json(
                    method="PATCH",
                    path=f"/api/v1/admin/providers/{recovered_id}",
                    json_body=payload,
                    headers=self._auth_headers(),
                    expect_dict=True,
                )
                if update_result.is_success and isinstance(update_result.data, dict):
                    parsed_remote_id = _to_uuid(update_result.data.get("id"))
                    if parsed_remote_id is not None:
                        return parsed_remote_id
                    return recovered_id

        if not create_result.is_success or not isinstance(create_result.data, dict):
            raise ProviderModelsServiceError(
                create_message
                or (
                    "Falha ao criar provider remoto na FastAPI "
                    f"(HTTP {create_result.status_code}, code={create_code})."
                )
            )

        created_id = _to_uuid(create_result.data.get("id"))
        if created_id is None:
            raise ProviderModelsServiceError(
                "FastAPI nao retornou ID valido ao sincronizar provider."
            )
        return created_id

    def _recover_provider_id_by_slug_conflict(self, *, slug: str) -> UUID | None:
        result = self.client.request_json(
            method="GET",
            path="/api/v1/admin/providers",
            headers=self._auth_headers(),
            expect_dict=False,
        )
        if not result.is_success or not isinstance(result.data, list):
            return None

        for item in result.data:
            if not isinstance(item, dict):
                continue
            remote_slug = str(item.get("slug") or "").strip().lower()
            if remote_slug != str(slug or "").strip().lower():
                continue
            remote_id = _to_uuid(item.get("id"))
            if remote_id is not None:
                logger.warning(
                    "Provider slug conflict recovered by exact slug lookup.",
                    extra={"provider_slug": slug, "recovered_remote_id": str(remote_id)},
                )
                return remote_id
        return None

    def create_remote_model(
        self,
        *,
        provider: Provider,
        model_name: str,
        model_slug: str,
        context_window: int | None,
        input_cost_per_1k: Decimal | None,
        output_cost_per_1k: Decimal | None,
        is_active: bool,
    ) -> dict[str, Any]:
        if provider.fastapi_provider_id is None:
            raise ProviderModelsServiceError(
                "Provider sem vinculo com FastAPI. Sincronize o provider antes de cadastrar modelos."
            )

        payload = {
            "model_name": str(model_name or "").strip(),
            "model_slug": str(model_slug or "").strip().lower(),
            "context_limit": int(context_window or 8192),
            "cost_input_per_1k_tokens": str(input_cost_per_1k or Decimal("0")),
            "cost_output_per_1k_tokens": str(output_cost_per_1k or Decimal("0")),
            "is_active": bool(is_active),
        }

        result = self.client.request_json(
            method="POST",
            path=f"/api/v1/admin/providers/{provider.fastapi_provider_id}/models",
            json_body=payload,
            headers=self._auth_headers(),
            expect_dict=True,
        )
        if not result.is_success or not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise ProviderModelsServiceError(
                message
                or f"Falha ao cadastrar modelo no catalogo da FastAPI (HTTP {result.status_code}, code={code})."
        )
        return result.data

    def update_remote_model(
        self,
        *,
        fastapi_model_id: UUID | None,
        context_window: int | None = None,
        input_cost_per_1k: Decimal | None = None,
        output_cost_per_1k: Decimal | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        if fastapi_model_id is None:
            raise ProviderModelsServiceError(
                "Modelo local sem vinculo com a FastAPI. Refaça o cadastro pelo fluxo integrado."
            )

        payload: dict[str, Any] = {
            "context_limit": int(context_window or 8192),
            "cost_input_per_1k_tokens": str(input_cost_per_1k or Decimal("0")),
            "cost_output_per_1k_tokens": str(output_cost_per_1k or Decimal("0")),
            "is_active": is_active,
        }

        result = self.client.request_json(
            method="PATCH",
            path=f"/api/v1/admin/models/{fastapi_model_id}",
            json_body=payload,
            headers=self._auth_headers(),
            expect_dict=True,
        )
        if not result.is_success or not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise ProviderModelsServiceError(
                message
                or (
                    "Falha ao atualizar modelo no catalogo da FastAPI "
                    f"(HTTP {result.status_code}, code={code})."
                )
            )
        return result.data

    def delete_remote_model(
        self,
        *,
        fastapi_model_id: UUID | None,
    ) -> bool:
        if fastapi_model_id is None:
            return False

        result = self.client.request_json(
            method="DELETE",
            path=f"/api/v1/admin/models/{fastapi_model_id}",
            headers=self._auth_headers(),
            expect_dict=True,
        )
        if result.is_success:
            return True

        code, message = self._extract_error_meta(result)
        if result.status_code == 404 and code == "provider_model_not_found":
            # Modelo nao existe mais no catalogo remoto. Permitimos limpeza local.
            return False

        raise ProviderModelsServiceError(
            message
            or (
                "Falha ao excluir modelo no catalogo da FastAPI "
                f"(HTTP {result.status_code}, code={code})."
            )
        )

    def _list_remote_provider_models(self, *, provider: Provider) -> list[dict[str, Any]]:
        if provider.fastapi_provider_id is None:
            return []

        result = self.client.request_json(
            method="GET",
            path=f"/api/v1/admin/providers/{provider.fastapi_provider_id}/models",
            headers=self._auth_headers(),
            expect_dict=False,
        )
        if not result.is_success:
            code, message = self._extract_error_meta(result)
            raise ProviderModelsServiceError(
                message
                or (
                    "Falha ao listar modelos do catalogo remoto na FastAPI "
                    f"(HTTP {result.status_code}, code={code})."
                )
            )
        return self._parse_model_payload(result, source="api_catalog")

    def _find_remote_model_ids_by_slug(
        self,
        *,
        provider: Provider,
        model_slug: str,
    ) -> list[UUID]:
        target_key = self._normalize_lookup_key(model_slug)
        if not target_key:
            return []

        candidates = self._list_remote_provider_models(provider=provider)
        remote_ids: list[UUID] = []
        for item in candidates:
            candidate_key = self._normalize_lookup_key(item.get("slug") or item.get("provider_model_id"))
            if candidate_key != target_key:
                continue
            candidate_id = _to_uuid(item.get("fastapi_model_id"))
            if candidate_id is None:
                continue
            if candidate_id not in remote_ids:
                remote_ids.append(candidate_id)
        return remote_ids

    def delete_remote_model_entry(
        self,
        *,
        provider: Provider,
        model_slug: str,
        fastapi_model_id: UUID | None,
    ) -> int:
        if provider.fastapi_provider_id is None:
            return 0

        normalized_slug_key = self._normalize_lookup_key(model_slug)
        if not normalized_slug_key:
            raise ProviderModelsServiceError(
                "Slug do modelo invalido para exclusao remota."
            )

        logger.info(
            "Iniciando exclusao remota de modelo por id/slug.",
            extra={
                "provider_id": provider.id,
                "provider_slug": provider.slug,
                "remote_provider_id": str(provider.fastapi_provider_id),
                "model_slug": model_slug,
                "fastapi_model_id": str(fastapi_model_id) if fastapi_model_id is not None else None,
            },
        )

        deleted_count = 0
        if self.delete_remote_model(fastapi_model_id=fastapi_model_id):
            deleted_count += 1

        remaining_ids = self._find_remote_model_ids_by_slug(
            provider=provider,
            model_slug=model_slug,
        )
        for remote_id in remaining_ids:
            if fastapi_model_id is not None and remote_id == fastapi_model_id:
                continue
            if self.delete_remote_model(fastapi_model_id=remote_id):
                deleted_count += 1

        final_remaining_ids = self._find_remote_model_ids_by_slug(
            provider=provider,
            model_slug=model_slug,
        )
        if final_remaining_ids:
            logger.error(
                "Exclusao remota incompleta: residuos encontrados por slug.",
                extra={
                    "provider_id": provider.id,
                    "provider_slug": provider.slug,
                    "remote_provider_id": str(provider.fastapi_provider_id),
                    "model_slug": model_slug,
                    "remaining_remote_ids": [str(item) for item in final_remaining_ids],
                },
            )
            raise ProviderModelsServiceError(
                "Ainda existem registros remotos para este modelo apos a tentativa de limpeza. "
                "A exclusao local foi bloqueada para manter consistencia."
            )

        logger.info(
            "Exclusao remota concluida sem residuos por slug.",
            extra={
                "provider_id": provider.id,
                "provider_slug": provider.slug,
                "remote_provider_id": str(provider.fastapi_provider_id),
                "model_slug": model_slug,
                "deleted_count": deleted_count,
            },
        )
        return deleted_count

    def get_available_models(self, *, provider: Provider) -> dict[str, Any]:
        warnings: list[str] = []

        remote_provider_id = provider.fastapi_provider_id
        if remote_provider_id is None:
            warnings.append(
                "Provider nao sincronizado com a FastAPI. Edite/salve o provider para criar o vinculo remoto."
            )
            return {
                "items": [],
                "source": "provider_not_synced",
                "warnings": _dedupe(warnings),
                "provider_remote_id": None,
            }

        available_result = self.client.request_json(
            method="GET",
            path=f"/api/v1/admin/providers/{remote_provider_id}/available-models",
            headers=self._auth_headers(),
            expect_dict=False,
        )

        if available_result.is_success:
            api_items = self._parse_model_payload(available_result, source="api_provider")
            api_items = self._with_known_model_metadata_fallback(
                provider=provider,
                items=api_items,
            )
            if api_items:
                return {
                    "items": api_items,
                    "source": "api_provider",
                    "warnings": _dedupe(warnings),
                    "provider_remote_id": str(remote_provider_id),
                }
            warnings.append("FastAPI nao retornou modelos disponiveis para este provider.")
            return {
                "items": [],
                "source": "api_provider",
                "warnings": _dedupe(warnings),
                "provider_remote_id": str(remote_provider_id),
            }

        if available_result.status_code == 404:
            catalog_result = self.client.request_json(
                method="GET",
                path=f"/api/v1/admin/providers/{remote_provider_id}/models",
                headers=self._auth_headers(),
                expect_dict=False,
            )
            if catalog_result.is_success:
                catalog_items = self._parse_model_payload(catalog_result, source="api_catalog")
                catalog_items = self._with_known_model_metadata_fallback(
                    provider=provider,
                    items=catalog_items,
                )
                return {
                    "items": catalog_items,
                    "source": "api_catalog",
                    "warnings": _dedupe(warnings),
                    "provider_remote_id": str(remote_provider_id),
                }

            if self._is_integration_failure(catalog_result):
                warnings.append(
                    self._format_provider_discovery_error(provider=provider, result=catalog_result)
                )
                fallback_items = self._fallback_items(provider)
                if fallback_items:
                    warnings.append(
                        "Fallback local ativado por falha real de integracao com FastAPI/provider."
                    )
                    return {
                        "items": fallback_items,
                        "source": "fallback_local",
                        "warnings": _dedupe(warnings),
                        "provider_remote_id": str(remote_provider_id),
                    }

            warnings.append(
                self._format_provider_discovery_error(provider=provider, result=catalog_result)
            )
            return {
                "items": [],
                "source": "unavailable",
                "warnings": _dedupe(warnings),
                "provider_remote_id": str(remote_provider_id),
            }

        if self._is_integration_failure(available_result):
            warnings.append(
                self._format_provider_discovery_error(provider=provider, result=available_result)
            )
            fallback_items = self._fallback_items(provider)
            if fallback_items:
                warnings.append(
                    "Fallback local ativado por falha real de integracao com FastAPI/provider."
                )
                logger.warning(
                    "Fallback local ativado por falha de integracao.",
                    extra={
                        "provider_id": provider.id,
                        "provider_slug": provider.slug,
                        "remote_provider_id": str(remote_provider_id),
                        "status_code": available_result.status_code,
                    },
                )
                return {
                    "items": fallback_items,
                    "source": "fallback_local",
                    "warnings": _dedupe(warnings),
                    "provider_remote_id": str(remote_provider_id),
                }

        warnings.append(
            self._format_provider_discovery_error(provider=provider, result=available_result)
        )
        return {
            "items": [],
            "source": "unavailable",
            "warnings": _dedupe(warnings),
            "provider_remote_id": str(remote_provider_id),
        }
