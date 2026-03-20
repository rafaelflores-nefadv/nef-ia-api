from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .api_client import FastAPIClient

SUPPORTED_ADMIN_STATUSES = {"em_andamento", "falhou"}


def _dedupe(values: list[str]) -> list[str]:
    unique: list[str] = []
    for item in values:
        normalized = str(item or "").strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def _status_meta(status: str) -> dict[str, str]:
    table = {
        "pendente": {"label": "Pendente", "css_class": "status-neutral"},
        "em_andamento": {"label": "Em andamento", "css_class": "status-warning"},
        "concluida": {"label": "Concluida", "css_class": "status-success"},
        "falhou": {"label": "Falhou", "css_class": "status-danger"},
    }
    return table.get(status, table["pendente"])


def _format_duration(total_seconds: int | None) -> str:
    if total_seconds is None or total_seconds < 0:
        return "-"

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


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


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_status(raw: str | None, fallback: str) -> str:
    status = str(raw or "").strip().lower()
    if status in {"failed", "error", "falhou"}:
        return "falhou"
    if status in {"completed", "done", "success", "concluida", "completed_success"}:
        return "concluida"
    if status in {"queued", "pending", "created", "pendente"}:
        return "pendente"
    if status in {"processing", "running", "in_progress", "generating_output", "em_andamento"}:
        return "em_andamento"
    return fallback


class ExecutionsService:
    def __init__(self):
        self.client = FastAPIClient()
        self.admin_token = self.client.admin_token

    def _auth_headers(self) -> dict[str, str] | None:
        return self.client.get_admin_headers()

    @staticmethod
    def _extract_error_message(data: Any, fallback: str = "") -> str:
        if isinstance(data, dict):
            error_payload = data.get("error")
            if isinstance(error_payload, dict):
                payload_message = str(error_payload.get("message") or "").strip()
                if payload_message:
                    return payload_message
        return str(fallback or "").strip()

    def _normalize_api_execution(
        self,
        row: dict[str, Any],
        *,
        fallback_status: str,
    ) -> dict[str, Any] | None:
        execution_id = str(row.get("execution_id") or row.get("id") or "").strip()
        if not execution_id:
            return None

        status = _normalize_status(str(row.get("status") or ""), fallback=fallback_status)
        started_at = _parse_dt(row.get("started_at") or row.get("created_at"))
        finished_at = _parse_dt(row.get("finished_at"))
        estimated_cost = _safe_float(row.get("estimated_cost"), default=None)

        automation_name = row.get("automation_name")
        if not automation_name:
            automation_name = row.get("automation_id") or row.get("analysis_request_id") or "-"

        summary = "Dados carregados da FastAPI."
        if status == "falhou" and row.get("error_message"):
            summary = "Execucao com falha reportada pelo backend."
        elif status == "em_andamento":
            summary = "Execucao em andamento no backend."

        return {
            "id": execution_id,
            "automation_name": str(automation_name),
            "provider": str(row.get("provider") or "-"),
            "model": str(row.get("model") or "-"),
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "estimated_cost": estimated_cost,
            "related_files_count": None,
            "processing_summary": summary,
            "error_message": str(row.get("error_message") or ""),
            "source": "api",
        }

    def _fetch_admin_execution_list(
        self,
        *,
        endpoint: str,
        fallback_status: str,
        limit: int,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        result = self.client.get(
            endpoint,
            params={"limit": limit},
            headers=self._auth_headers(),
            expect_dict=True,
        )

        if result.status_code in {401, 403} and not self.admin_token:
            warnings.append("Configure o token administrativo da FastAPI nas configuracoes.")
        elif result.status_code in {401, 403} and self.admin_token:
            warnings.append("Token administrativo invalido ou sem permissao para consultar execucoes.")
        elif result.status_code is None:
            warnings.append(str(result.error or "Falha de conexao com a FastAPI ao consultar execucoes."))
        elif result.error:
            warnings.append(str(result.error))

        items_payload: list[Any] = []
        if isinstance(result.data, dict):
            raw_items = result.data.get("items")
            if isinstance(raw_items, list):
                items_payload = raw_items

        normalized: list[dict[str, Any]] = []
        for raw in items_payload:
            if not isinstance(raw, dict):
                continue
            item = self._normalize_api_execution(raw, fallback_status=fallback_status)
            if item is not None:
                normalized.append(item)

        reachable = result.status_code is not None
        return {
            "items": normalized,
            "warnings": warnings,
            "status_code": result.status_code,
            "reachable": reachable,
        }

    def _load_execution_pool(self, *, limit: int = 200) -> dict[str, Any]:
        running = self._fetch_admin_execution_list(
            endpoint="/api/v1/admin/executions/running",
            fallback_status="em_andamento",
            limit=limit,
        )
        failed = self._fetch_admin_execution_list(
            endpoint="/api/v1/admin/executions/failed",
            fallback_status="falhou",
            limit=limit,
        )

        warnings = _dedupe(running["warnings"] + failed["warnings"])
        api_items = running["items"] + failed["items"]

        deduped: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in api_items:
            execution_id = str(item.get("id") or "").strip()
            if not execution_id or execution_id in seen_ids:
                continue
            seen_ids.add(execution_id)
            deduped.append(item)

        reachable = bool(running["reachable"] or failed["reachable"])
        source = "api" if reachable else "unavailable"

        if reachable and not deduped:
            warnings.append(
                "A API administrativa nao retornou execucoes em andamento/falha para o recorte atual."
            )
            warnings.append(
                "Pendentes/concluidas dependem de endpoint remoto adicional para listagem administrativa completa."
            )
        if not reachable:
            warnings.append(
                "Nao foi possivel consultar execucoes na API. Nenhum fallback local foi aplicado."
            )

        return {
            "items": deduped,
            "source": source,
            "warnings": _dedupe(warnings),
        }

    def _apply_filters(
        self,
        items: list[dict[str, Any]],
        *,
        status: str,
        provider: str,
        period: str,
        query: str,
        now: datetime,
    ) -> list[dict[str, Any]]:
        filtered = items

        if status:
            filtered = [item for item in filtered if item.get("status") == status]

        if provider:
            filtered = [item for item in filtered if item.get("provider") == provider]

        if period:
            period_map = {"24h": 1, "7d": 7, "30d": 30}
            days = period_map.get(period)
            if days:
                cutoff = now - timedelta(days=days)
                filtered = [
                    item
                    for item in filtered
                    if item.get("started_at") and item["started_at"] >= cutoff
                ]

        if query:
            lowered = query.lower()
            filtered = [
                item
                for item in filtered
                if lowered in str(item.get("id", "")).lower()
                or lowered in str(item.get("automation_name", "")).lower()
            ]

        return filtered

    def _build_view_item(self, execution: dict[str, Any], now: datetime) -> dict[str, Any]:
        started_at = execution.get("started_at")
        finished_at = execution.get("finished_at")

        if isinstance(started_at, datetime) and isinstance(finished_at, datetime):
            total_seconds = int((finished_at - started_at).total_seconds())
        elif isinstance(started_at, datetime) and execution.get("status") in {"em_andamento", "pendente"}:
            total_seconds = int((now - started_at).total_seconds())
        else:
            total_seconds = None

        meta = _status_meta(str(execution.get("status") or "pendente"))
        estimated_cost = _safe_float(execution.get("estimated_cost"), default=None)
        cost_display = "-" if estimated_cost is None else f"US$ {estimated_cost:.4f}"

        return {
            **execution,
            "status_label": meta["label"],
            "status_css_class": meta["css_class"],
            "duration_display": _format_duration(total_seconds),
            "cost_display": cost_display,
            "has_error": bool(execution.get("error_message")),
        }

    def _fetch_related_files_count(self, execution_id: str) -> dict[str, Any]:
        warnings: list[str] = []
        result = self.client.get(
            f"/api/v1/admin/executions/{execution_id}/files",
            headers=self._auth_headers(),
            expect_dict=True,
        )
        if result.status_code is None:
            warnings.append(str(result.error or "Falha ao consultar arquivos da execucao."))
            return {"count": None, "warnings": warnings}
        if result.status_code in {401, 403}:
            warnings.append("Sem permissao para consultar arquivos relacionados desta execucao.")
            return {"count": None, "warnings": warnings}
        if result.status_code == 404:
            warnings.append("Execucao nao encontrada ao consultar arquivos relacionados.")
            return {"count": None, "warnings": warnings}
        if result.error:
            warnings.append(str(result.error))
            return {"count": None, "warnings": warnings}

        items = result.data.get("items", []) if isinstance(result.data, dict) else []
        if isinstance(items, list):
            return {"count": len(items), "warnings": warnings}

        warnings.append("Resposta inesperada ao consultar arquivos relacionados.")
        return {"count": None, "warnings": warnings}

    def get_execution_list(
        self,
        *,
        status: str = "",
        provider: str = "",
        period: str = "",
        query: str = "",
    ) -> dict[str, Any]:
        now = timezone.localtime()
        pool = self._load_execution_pool(limit=200)
        warnings = list(pool["warnings"])

        if status and status not in SUPPORTED_ADMIN_STATUSES:
            warnings.append(
                "A API administrativa atual lista apenas execucoes em andamento/falha. "
                "Para pendente/concluida, backend precisa expor endpoint dedicado."
            )

        filtered = self._apply_filters(
            pool["items"],
            status=status,
            provider=provider,
            period=period,
            query=query,
            now=now,
        )
        prepared = [self._build_view_item(item, now) for item in filtered]

        fallback_dt = timezone.make_aware(datetime(1970, 1, 1), timezone.get_current_timezone())
        prepared.sort(
            key=lambda item: item.get("started_at") or fallback_dt,
            reverse=True,
        )

        provider_options = sorted(
            {
                str(item.get("provider") or "-")
                for item in pool["items"]
                if str(item.get("provider") or "").strip()
            }
        )

        return {
            "items": prepared,
            "provider_options": provider_options,
            "warnings": _dedupe(warnings),
            "source": pool["source"],
            "filtered_count": len(prepared),
            "total_count": len(pool["items"]),
        }

    def get_execution_detail(self, execution_id: str) -> dict[str, Any]:
        now = timezone.localtime()
        pool = self._load_execution_pool(limit=200)
        warnings = list(pool["warnings"])

        execution = next((item for item in pool["items"] if item.get("id") == execution_id), None)
        if not execution:
            return {
                "found": False,
                "execution": None,
                "warnings": _dedupe(warnings),
                "source": pool["source"],
                "limitation_message": (
                    "Execucao nao localizada no catalogo administrativo remoto (running/failed). "
                    "Backend precisa expor endpoint de detalhe completo para todos os status."
                ),
            }

        files_info = self._fetch_related_files_count(execution_id)
        if files_info["count"] is not None:
            execution["related_files_count"] = files_info["count"]
        warnings.extend(files_info["warnings"])

        prepared = self._build_view_item(execution, now)
        limitation_message = None
        if prepared.get("related_files_count") is None:
            limitation_message = (
                "Quantidade de arquivos relacionados indisponivel no momento."
            )

        return {
            "found": True,
            "execution": prepared,
            "warnings": _dedupe(warnings),
            "source": pool["source"],
            "limitation_message": limitation_message,
        }
