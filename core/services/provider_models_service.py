from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.utils.text import slugify

from models_catalog.catalog import get_known_models
from providers.models import Provider

from .api_client import FastAPIClient

logger = logging.getLogger(__name__)


def _dedupe(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
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


class ProviderModelsService:
    def __init__(self):
        self.client = FastAPIClient()
        self.admin_token = (getattr(settings, "FASTAPI_ADMIN_TOKEN", "") or "").strip()

    def _auth_headers(self) -> dict[str, str] | None:
        if not self.admin_token:
            return None
        return {"Authorization": f"Bearer {self.admin_token}"}

    def _fallback_items(self, provider: Provider) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for model in get_known_models(provider.slug):
            items.append(
                {
                    "key": model.key,
                    "label": model.label,
                    "name": model.name,
                    "slug": model.slug,
                    "context_window": model.context_window,
                    "input_cost_per_1k": model.input_cost_per_1k,
                    "output_cost_per_1k": model.output_cost_per_1k,
                    "description": model.description,
                }
            )
        return items

    def _fetch_admin_providers(self) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        result = self.client.get_json(
            "/api/v1/admin/providers",
            headers=self._auth_headers(),
            expect_dict=False,
        )

        if result.status_code in {401, 403} and not self.admin_token:
            warnings.append(
                "Configure FASTAPI_ADMIN_TOKEN para consultar providers administrativos."
            )
            return [], warnings
        if result.status_code in {401, 403} and self.admin_token:
            warnings.append("Token administrativo invalido ou sem permissao para providers.")
            return [], warnings
        if result.status_code is None:
            warnings.append(result.error or "Falha de conexao com a FastAPI.")
            return [], warnings
        if result.error:
            warnings.append(result.error)

        if isinstance(result.data, list):
            return [item for item in result.data if isinstance(item, dict)], warnings

        warnings.append("Resposta inesperada ao consultar providers administrativos.")
        return [], warnings

    def _match_remote_provider_id(
        self,
        *,
        provider: Provider,
        remote_providers: list[dict[str, Any]],
    ) -> str | None:
        local_slug = (provider.slug or "").strip().lower()
        local_name_slug = slugify(provider.name)

        for row in remote_providers:
            remote_slug = str(row.get("slug") or "").strip().lower()
            remote_name_slug = slugify(str(row.get("name") or ""))
            if remote_slug and remote_slug == local_slug:
                return str(row.get("id") or "")
            if remote_name_slug and remote_name_slug == local_name_slug:
                return str(row.get("id") or "")
        return None

    def _normalize_model_item(self, row: dict[str, Any]) -> dict[str, Any] | None:
        raw_name = row.get("model_name") or row.get("name") or row.get("label") or row.get("id")
        raw_slug = row.get("model_slug") or row.get("slug") or row.get("id") or raw_name

        name = str(raw_name or "").strip()
        slug = str(raw_slug or "").strip().lower()

        if not name and slug:
            name = slug
        if not slug and name:
            slug = slugify(name)
        if not name or not slug:
            return None

        label = str(row.get("label") or name).strip() or name
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
        raw_is_registered = row.get("is_registered")
        is_registered = False
        if isinstance(raw_is_registered, bool):
            is_registered = raw_is_registered
        elif isinstance(raw_is_registered, str):
            is_registered = raw_is_registered.strip().lower() in {"1", "true", "yes", "sim"}
        elif isinstance(raw_is_registered, (int, float)):
            is_registered = bool(raw_is_registered)

        return {
            "key": slug,
            "label": label,
            "name": name,
            "slug": slug,
            "context_window": context_window,
            "input_cost_per_1k": input_cost,
            "output_cost_per_1k": output_cost,
            "description": description,
            "is_registered": is_registered,
        }

    def _fetch_models_from_fastapi(
        self,
        *,
        remote_provider_id: str,
    ) -> tuple[list[dict[str, Any]], str | None, list[str]]:
        warnings: list[str] = []
        candidates = [
            (
                f"/api/v1/admin/providers/{remote_provider_id}/available-models",
                "api_provider",
            ),
            (
                f"/api/v1/admin/providers/{remote_provider_id}/models",
                "api_catalog",
            ),
        ]

        for path, source in candidates:
            result = self.client.get_json(
                path,
                headers=self._auth_headers(),
                expect_dict=False,
            )

            if result.status_code == 404:
                if source == "api_catalog":
                    warnings.append(
                        "Endpoint administrativo de modelos nao disponivel nesta versao da API."
                    )
                continue

            if result.status_code in {401, 403} and not self.admin_token:
                warnings.append(
                    "Configure FASTAPI_ADMIN_TOKEN para consultar modelos disponiveis."
                )
                return [], None, warnings
            if result.status_code in {401, 403} and self.admin_token:
                warnings.append("Token administrativo invalido ou sem permissao para modelos.")
                return [], None, warnings
            if result.status_code is None:
                warnings.append(result.error or "Falha de conexao com a FastAPI.")
                return [], None, warnings
            if result.error:
                warnings.append(result.error)
                continue

            raw_items: list[dict[str, Any]] = []
            if isinstance(result.data, list):
                raw_items = [item for item in result.data if isinstance(item, dict)]
            elif isinstance(result.data, dict):
                candidate_items = result.data.get("items")
                if isinstance(candidate_items, list):
                    raw_items = [
                        item for item in candidate_items if isinstance(item, dict)
                    ]

            normalized: list[dict[str, Any]] = []
            for row in raw_items:
                item = self._normalize_model_item(row)
                if item:
                    normalized.append(item)

            deduped: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in normalized:
                if item["slug"] in seen:
                    continue
                seen.add(item["slug"])
                if source == "api_catalog":
                    item["is_registered"] = True
                deduped.append(item)

            return deduped, source, warnings

        return [], None, warnings

    def get_available_models(self, *, provider: Provider) -> dict[str, Any]:
        warnings: list[str] = []
        fallback_reason = "api_error"

        remote_providers, provider_warnings = self._fetch_admin_providers()
        warnings.extend(provider_warnings)
        remote_provider_id = self._match_remote_provider_id(
            provider=provider,
            remote_providers=remote_providers,
        )

        api_items: list[dict[str, Any]] = []
        source = None

        if remote_provider_id:
            api_items, source, model_warnings = self._fetch_models_from_fastapi(
                remote_provider_id=remote_provider_id
            )
            warnings.extend(model_warnings)
            if not api_items:
                if model_warnings:
                    fallback_reason = "api_error"
                else:
                    fallback_reason = "api_no_data"
        else:
            warnings.append(
                "Provider local nao encontrado no catalogo administrativo da FastAPI."
            )
            fallback_reason = "provider_not_found"

        if api_items:
            if source == "api_provider":
                source_label = "api_provider"
                logger.info(
                    "Modelos carregados via descoberta do provider.",
                    extra={
                        "provider_slug": provider.slug,
                        "provider_id": provider.id,
                        "remote_provider_id": remote_provider_id,
                        "source": source_label,
                        "items_count": len(api_items),
                    },
                )
            else:
                source_label = "api_catalog"
                warnings.append(
                    "A API nao retornou descoberta direta do provider nesta consulta."
                )
                logger.info(
                    "Modelos carregados via catalogo administrativo da FastAPI.",
                    extra={
                        "provider_slug": provider.slug,
                        "provider_id": provider.id,
                        "remote_provider_id": remote_provider_id,
                        "source": source_label,
                        "items_count": len(api_items),
                    },
                )
            return {
                "items": api_items,
                "source": source_label,
                "warnings": _dedupe(warnings),
                "provider_remote_id": remote_provider_id,
            }

        fallback_items = self._fallback_items(provider)
        if fallback_items:
            warnings.append("Exibindo catalogo local como fallback temporario.")
            if fallback_reason == "api_no_data":
                logger.info(
                    "Fallback local ativado por ausencia de dados da API.",
                    extra={
                        "provider_slug": provider.slug,
                        "provider_id": provider.id,
                        "remote_provider_id": remote_provider_id,
                        "source": "fallback_local",
                        "fallback_reason": fallback_reason,
                        "items_count": len(fallback_items),
                    },
                )
            else:
                logger.warning(
                    "Fallback local ativado por erro de integracao administrativa.",
                    extra={
                        "provider_slug": provider.slug,
                        "provider_id": provider.id,
                        "remote_provider_id": remote_provider_id,
                        "source": "fallback_local",
                        "fallback_reason": fallback_reason,
                        "items_count": len(fallback_items),
                    },
                )
            return {
                "items": fallback_items,
                "source": "fallback_local",
                "warnings": _dedupe(warnings),
                "provider_remote_id": remote_provider_id,
            }

        warnings.append("Nenhum modelo disponivel foi retornado para este provider.")
        logger.warning(
            "Nenhum modelo disponivel na API e no fallback local.",
            extra={
                "provider_slug": provider.slug,
                "provider_id": provider.id,
                "remote_provider_id": remote_provider_id,
                "source": "unavailable",
                "fallback_reason": fallback_reason,
            },
        )
        return {
            "items": [],
            "source": "unavailable",
            "warnings": _dedupe(warnings),
            "provider_remote_id": remote_provider_id,
        }
