from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .api_client import FastAPIClient
from .executions_service import ExecutionsService


MAX_EXECUTIONS_FOR_FILE_AGGREGATION = 40


def _dedupe(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
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


def _safe_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _format_size(size_bytes: int | None) -> str:
    if size_bytes is None or size_bytes < 0:
        return "-"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _status_meta(status: str) -> dict[str, str]:
    mapping = {
        "disponivel": {"label": "Disponível", "css_class": "status-success"},
        "processando": {"label": "Processando", "css_class": "status-warning"},
        "erro": {"label": "Erro", "css_class": "status-danger"},
        "arquivado": {"label": "Arquivado", "css_class": "status-neutral"},
    }
    return mapping.get(status, mapping["disponivel"])


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


class FilesService:
    def __init__(self):
        self.client = FastAPIClient()
        self.executions_service = ExecutionsService()
        self.admin_token = (getattr(settings, "FASTAPI_ADMIN_TOKEN", "") or "").strip()

    def _auth_headers(self) -> dict[str, str] | None:
        if not self.admin_token:
            return None
        return {"Authorization": f"Bearer {self.admin_token}"}

    def _mock_files(self) -> list[dict[str, Any]]:
        now = timezone.localtime()
        return [
            {
                "id": "file-9001",
                "name": "nfes_marco_2026.xlsx",
                "type": "xlsx",
                "size_bytes": 1_842_744,
                "execution_id": "exec-1001",
                "status": "disponivel",
                "created_at": now - timedelta(hours=2, minutes=20),
                "source": "upload manual",
                "summary": "Planilha consolidada para extração tributária.",
                "storage_path": "/mock/storage/nfes_marco_2026.xlsx",
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "checksum": None,
                "error_message": "",
                "origin_kind": "mock",
            },
            {
                "id": "file-9002",
                "name": "compras_lote_a.pdf",
                "type": "pdf",
                "size_bytes": 734_920,
                "execution_id": "exec-1002",
                "status": "processando",
                "created_at": now - timedelta(minutes=26),
                "source": "api inbound",
                "summary": "Documento em análise para classificação de compras.",
                "storage_path": "/mock/storage/compras_lote_a.pdf",
                "mime_type": "application/pdf",
                "checksum": None,
                "error_message": "",
                "origin_kind": "mock",
            },
            {
                "id": "file-9003",
                "name": "reconciliacao_tributaria.json",
                "type": "json",
                "size_bytes": 88_121,
                "execution_id": "exec-1003",
                "status": "erro",
                "created_at": now - timedelta(hours=5, minutes=7),
                "source": "worker",
                "summary": "Falha ao validar esquema de dados de reconciliação.",
                "storage_path": "/mock/storage/reconciliacao_tributaria.json",
                "mime_type": "application/json",
                "checksum": None,
                "error_message": "Schema inválido no campo total_retido.",
                "origin_kind": "mock",
            },
            {
                "id": "file-9004",
                "name": "pagamentos_abril.csv",
                "type": "csv",
                "size_bytes": 12_210_901,
                "execution_id": "exec-1004",
                "status": "arquivado",
                "created_at": now - timedelta(days=3, hours=2),
                "source": "sftp import",
                "summary": "Arquivo histórico de pagamentos pronto para auditoria.",
                "storage_path": "/mock/storage/pagamentos_abril.csv",
                "mime_type": "text/csv",
                "checksum": None,
                "error_message": "",
                "origin_kind": "mock",
            },
            {
                "id": "file-9005",
                "name": "sumario_operacional.txt",
                "type": "txt",
                "size_bytes": 15_840,
                "execution_id": "exec-1005",
                "status": "disponivel",
                "created_at": now - timedelta(days=1, hours=1, minutes=50),
                "source": "gerado pelo sistema",
                "summary": "Resumo textual com indicadores operacionais da execução.",
                "storage_path": "/mock/storage/sumario_operacional.txt",
                "mime_type": "text/plain",
                "checksum": None,
                "error_message": "",
                "origin_kind": "mock",
            },
        ]

    def _derive_status(
        self,
        *,
        file_type: str,
        file_name: str,
        execution_status: str | None,
    ) -> str:
        normalized_type = file_type.lower()
        normalized_name = file_name.lower()

        if normalized_type == "error" or "_error" in normalized_name:
            return "erro"
        if normalized_type in {"debug", "intermediate"}:
            return "processando"
        if execution_status in {"em_andamento", "pendente"}:
            return "processando"
        if execution_status == "falhou":
            return "erro"
        return "disponivel"

    def _normalize_api_file(
        self,
        row: dict[str, Any],
        *,
        execution_id: str,
        execution_status: str | None,
    ) -> dict[str, Any] | None:
        file_id = str(row.get("id") or "").strip()
        if not file_id:
            return None

        file_name = str(row.get("file_name") or "-")
        file_type = str(row.get("file_type") or "").strip().lower()
        if not file_type and "." in file_name:
            file_type = file_name.rsplit(".", 1)[-1].lower()
        file_type = file_type or "-"

        status = self._derive_status(
            file_type=file_type,
            file_name=file_name,
            execution_status=execution_status,
        )

        summary = f"Arquivo {file_type} retornado pela FastAPI para a execução."
        error_message = ""
        if status == "erro":
            error_message = "Arquivo de erro associado à execução."
            summary = "Arquivo de erro retornado pelo backend."

        return {
            "id": file_id,
            "name": file_name,
            "type": file_type,
            "size_bytes": _safe_int(row.get("file_size")),
            "execution_id": execution_id,
            "status": status,
            "created_at": _parse_dt(row.get("created_at")),
            "source": "api execution files",
            "summary": summary,
            "storage_path": str(row.get("file_path") or "-"),
            "mime_type": row.get("mime_type"),
            "checksum": row.get("checksum"),
            "error_message": error_message,
            "origin_kind": "api",
        }

    def _fetch_files_for_execution(
        self,
        *,
        execution_id: str,
        execution_status: str | None,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        result = self.client.get_json(
            f"/api/v1/admin/executions/{execution_id}/files",
            headers=self._auth_headers(),
        )

        if result.status_code in {401, 403} and not self.admin_token:
            warnings.append(
                "Configure FASTAPI_ADMIN_TOKEN para consumir arquivos administrativos reais."
            )
        elif result.status_code in {401, 403} and self.admin_token:
            warnings.append("Token administrativo inválido ou sem permissão para arquivos.")
        elif result.status_code is None:
            warnings.append(result.error or "Falha de conexão com a FastAPI ao consultar arquivos.")
        elif result.error:
            warnings.append(result.error)

        payload_items = result.data.get("items", []) if isinstance(result.data, dict) else []
        normalized: list[dict[str, Any]] = []
        if isinstance(payload_items, list):
            for raw in payload_items:
                if not isinstance(raw, dict):
                    continue
                item = self._normalize_api_file(
                    raw,
                    execution_id=execution_id,
                    execution_status=execution_status,
                )
                if item:
                    normalized.append(item)

        return {"items": normalized, "warnings": warnings}

    def _collect_real_files(self) -> dict[str, Any]:
        warnings: list[str] = []
        payload = self.executions_service.get_execution_list()
        warnings.extend(payload.get("warnings", []))

        execution_items = payload.get("items", [])
        api_executions = [
            item
            for item in execution_items
            if str(item.get("source")) == "api" and _is_uuid(str(item.get("id", "")))
        ]

        if len(api_executions) > MAX_EXECUTIONS_FOR_FILE_AGGREGATION:
            warnings.append(
                f"Agregação limitada a {MAX_EXECUTIONS_FOR_FILE_AGGREGATION} execuções para preservar desempenho."
            )
        api_executions = api_executions[:MAX_EXECUTIONS_FOR_FILE_AGGREGATION]

        all_items: list[dict[str, Any]] = []
        for execution in api_executions:
            fetch_payload = self._fetch_files_for_execution(
                execution_id=str(execution.get("id")),
                execution_status=str(execution.get("status") or ""),
            )
            all_items.extend(fetch_payload["items"])
            warnings.extend(fetch_payload["warnings"])

        deduped: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in all_items:
            if item["id"] in seen_ids:
                continue
            seen_ids.add(item["id"])
            deduped.append(item)

        return {"items": deduped, "warnings": _dedupe(warnings)}

    def _load_file_pool(self) -> dict[str, Any]:
        real_payload = self._collect_real_files()
        real_items = real_payload["items"]
        warnings = list(real_payload["warnings"])

        if real_items:
            return {
                "items": real_items,
                "source": "api",
                "warnings": _dedupe(warnings),
            }

        warnings.append(
            "Arquivos reais indisponíveis no momento. Exibindo fallback local."
        )
        return {
            "items": self._mock_files(),
            "source": "mock",
            "warnings": _dedupe(warnings),
        }

    def _apply_filters(
        self,
        items: list[dict[str, Any]],
        *,
        status: str,
        file_type: str,
        execution_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        filtered = items

        if status:
            filtered = [item for item in filtered if item.get("status") == status]

        if file_type:
            filtered = [item for item in filtered if item.get("type") == file_type]

        if execution_id:
            filtered = [item for item in filtered if item.get("execution_id") == execution_id]

        if query:
            lowered = query.lower()
            filtered = [
                item
                for item in filtered
                if lowered in str(item.get("id", "")).lower()
                or lowered in str(item.get("name", "")).lower()
            ]

        return filtered

    def _build_view_item(self, file_item: dict[str, Any]) -> dict[str, Any]:
        status = str(file_item.get("status") or "disponivel")
        meta = _status_meta(status)
        return {
            **file_item,
            "status_label": meta["label"],
            "status_css_class": meta["css_class"],
            "size_display": _format_size(_safe_int(file_item.get("size_bytes"))),
            "has_error": bool(file_item.get("error_message")),
        }

    def get_files_list(
        self,
        *,
        status: str = "",
        file_type: str = "",
        execution_id: str = "",
        query: str = "",
    ) -> dict[str, Any]:
        pool = self._load_file_pool()
        filtered = self._apply_filters(
            pool["items"],
            status=status,
            file_type=file_type,
            execution_id=execution_id,
            query=query,
        )
        prepared = [self._build_view_item(item) for item in filtered]
        fallback_dt = timezone.make_aware(datetime(1970, 1, 1), timezone.get_current_timezone())
        prepared.sort(key=lambda item: item.get("created_at") or fallback_dt, reverse=True)

        type_options = sorted(
            {str(item.get("type") or "-") for item in pool["items"] if str(item.get("type") or "").strip()}
        )
        execution_options = sorted(
            {
                str(item.get("execution_id") or "-")
                for item in pool["items"]
                if str(item.get("execution_id") or "").strip()
            }
        )

        return {
            "items": prepared,
            "warnings": pool["warnings"],
            "source": pool["source"],
            "type_options": type_options,
            "execution_options": execution_options,
            "filtered_count": len(prepared),
            "total_count": len(pool["items"]),
        }

    def get_file_detail(self, file_id: str) -> dict[str, Any]:
        pool = self._load_file_pool()
        warnings = list(pool["warnings"])

        file_item = next((item for item in pool["items"] if item.get("id") == file_id), None)
        if file_item is None:
            return {
                "found": False,
                "file_item": None,
                "warnings": _dedupe(warnings),
                "source": pool["source"],
                "limitation_message": "Arquivo não localizado nos dados disponíveis.",
            }

        prepared = self._build_view_item(file_item)
        limitation_message = None
        if pool["source"] == "mock":
            limitation_message = "Detalhe exibido em fallback local por indisponibilidade da API."
        elif prepared.get("storage_path") in {"", "-"}:
            limitation_message = "Nem todos os campos técnicos do arquivo foram retornados pela API."

        return {
            "found": True,
            "file_item": prepared,
            "warnings": _dedupe(warnings),
            "source": pool["source"],
            "limitation_message": limitation_message,
        }
