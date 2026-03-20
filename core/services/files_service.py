from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .api_client import FastAPIClient
from .executions_service import ExecutionsService

MAX_EXECUTIONS_FOR_FILE_AGGREGATION = 200


def _dedupe(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
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
        "disponivel": {"label": "Disponivel", "css_class": "status-success"},
        "processando": {"label": "Processando", "css_class": "status-warning"},
        "erro": {"label": "Erro", "css_class": "status-danger"},
        "arquivado": {"label": "Arquivado", "css_class": "status-neutral"},
    }
    return mapping.get(status, mapping["disponivel"])


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
        return True
    except ValueError:
        return False


class FilesService:
    def __init__(self):
        self.client = FastAPIClient()
        self.executions_service = ExecutionsService()
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

        summary = f"Arquivo {file_type} retornado pela FastAPI para a execucao."
        error_message = ""
        if status == "erro":
            error_message = "Arquivo de erro associado a execucao."
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
        result = self.client.get(
            f"/api/v1/admin/executions/{execution_id}/files",
            headers=self._auth_headers(),
            expect_dict=True,
        )
        reachable = result.status_code is not None

        if result.status_code in {401, 403} and not self.admin_token:
            warnings.append("Configure o token administrativo da FastAPI nas configuracoes.")
        elif result.status_code in {401, 403} and self.admin_token:
            warnings.append("Token administrativo invalido ou sem permissao para arquivos.")
        elif result.status_code == 404:
            warnings.append(f"Execucao {execution_id} nao encontrada na API ao consultar arquivos.")
        elif result.status_code is None:
            warnings.append(
                str(result.error or "Falha de conexao com a FastAPI ao consultar arquivos.")
            )
        elif result.error:
            warnings.append(str(result.error))

        payload_items: list[Any] = []
        if isinstance(result.data, dict):
            raw_items = result.data.get("items")
            if isinstance(raw_items, list):
                payload_items = raw_items

        normalized: list[dict[str, Any]] = []
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

        return {"items": normalized, "warnings": warnings, "reachable": reachable}

    def _collect_real_files(
        self,
        *,
        execution_id_filter: str = "",
    ) -> dict[str, Any]:
        warnings: list[str] = []
        execution_filter = str(execution_id_filter or "").strip()

        if execution_filter:
            if not _is_uuid(execution_filter):
                return {
                    "items": [],
                    "warnings": [f"ID de execucao invalido para consulta remota: {execution_filter}."],
                    "reachable": False,
                }
            payload = self._fetch_files_for_execution(
                execution_id=execution_filter,
                execution_status=None,
            )
            return {
                "items": payload["items"],
                "warnings": _dedupe(payload["warnings"]),
                "reachable": bool(payload["reachable"]),
            }

        executions_payload = self.executions_service.get_execution_list()
        warnings.extend(executions_payload.get("warnings", []))
        any_reachable = executions_payload.get("source") == "api"

        execution_items = executions_payload.get("items", [])
        api_executions = [
            item
            for item in execution_items
            if str(item.get("source")) == "api" and _is_uuid(str(item.get("id", "")))
        ]

        if len(api_executions) > MAX_EXECUTIONS_FOR_FILE_AGGREGATION:
            warnings.append(
                f"Agregacao limitada a {MAX_EXECUTIONS_FOR_FILE_AGGREGATION} execucoes para preservar desempenho."
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
            any_reachable = any_reachable or bool(fetch_payload["reachable"])

        deduped: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in all_items:
            file_id = str(item.get("id") or "").strip()
            if not file_id or file_id in seen_ids:
                continue
            seen_ids.add(file_id)
            deduped.append(item)

        if not deduped:
            warnings.append(
                "A API nao retornou arquivos para as execucoes administrativas disponiveis no momento."
            )
        if not any_reachable:
            warnings.append(
                "Nao foi possivel consultar arquivos na API. Nenhum fallback local foi aplicado."
            )

        return {"items": deduped, "warnings": _dedupe(warnings), "reachable": any_reachable}

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
        file_id = str(file_item.get("id") or "").strip()
        return {
            **file_item,
            "status_label": meta["label"],
            "status_css_class": meta["css_class"],
            "size_display": _format_size(_safe_int(file_item.get("size_bytes"))),
            "has_error": bool(file_item.get("error_message")),
            "download_available": _is_uuid(file_id),
        }

    def get_files_list(
        self,
        *,
        status: str = "",
        file_type: str = "",
        execution_id: str = "",
        query: str = "",
    ) -> dict[str, Any]:
        pool = self._collect_real_files(execution_id_filter=execution_id)
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
            {
                str(item.get("type") or "-")
                for item in pool["items"]
                if str(item.get("type") or "").strip()
            }
        )
        execution_options = sorted(
            {
                str(item.get("execution_id") or "-")
                for item in pool["items"]
                if str(item.get("execution_id") or "").strip()
            }
        )
        if execution_id and execution_id not in execution_options and _is_uuid(execution_id):
            execution_options.append(execution_id)
            execution_options = sorted(execution_options)

        return {
            "items": prepared,
            "warnings": pool["warnings"],
            "source": "api" if pool.get("reachable") else "unavailable",
            "type_options": type_options,
            "execution_options": execution_options,
            "filtered_count": len(prepared),
            "total_count": len(pool["items"]),
        }

    def get_file_detail(self, file_id: str) -> dict[str, Any]:
        pool = self._collect_real_files()
        warnings = list(pool["warnings"])

        file_item = next((item for item in pool["items"] if item.get("id") == file_id), None)
        if file_item is None:
            return {
                "found": False,
                "file_item": None,
                "warnings": _dedupe(warnings),
                "source": "api" if pool.get("reachable") else "unavailable",
                "limitation_message": (
                    "Arquivo nao localizado no agregador remoto atual. "
                    "Backend precisa de endpoint administrativo de detalhe por file_id para cobertura completa."
                ),
            }

        prepared = self._build_view_item(file_item)
        limitation_message = None
        if not prepared.get("download_available"):
            limitation_message = (
                "ID de arquivo nao compativel com endpoint remoto de download."
            )
        elif prepared.get("storage_path") in {"", "-"}:
            limitation_message = "Nem todos os campos tecnicos do arquivo foram retornados pela API."

        return {
            "found": True,
            "file_item": prepared,
            "warnings": _dedupe(warnings),
            "source": "api" if pool.get("reachable") else "unavailable",
            "limitation_message": limitation_message,
        }

    def download_execution_file(self, *, file_id: str) -> dict[str, Any]:
        normalized_file_id = str(file_id or "").strip()
        if not _is_uuid(normalized_file_id):
            return {
                "ok": False,
                "error": "ID de arquivo invalido para download remoto.",
                "status_code": 400,
            }

        response = self.client.request_raw(
            method="GET",
            path=f"/api/v1/files/execution-files/{normalized_file_id}/download",
            headers=self._auth_headers(),
        )

        if not response.is_success:
            if response.status_code in {401, 403}:
                return {
                    "ok": False,
                    "error": (
                        "Falha de autenticacao/permissao no download remoto. "
                        "A API pode exigir token operacional de API para este endpoint."
                    ),
                    "status_code": response.status_code,
                }
            if response.status_code == 404:
                return {
                    "ok": False,
                    "error": "Arquivo nao encontrado na API para download.",
                    "status_code": response.status_code,
                }
            return {
                "ok": False,
                "error": str(
                    response.error
                    or f"Falha no download remoto do arquivo (HTTP {response.status_code})."
                ),
                "status_code": response.status_code,
            }

        headers = response.headers or {}
        content_type = str(headers.get("content-type") or "application/octet-stream")
        checksum = str(headers.get("x-file-checksum") or "").strip() or None

        filename = f"{normalized_file_id}.bin"
        content_disposition = str(headers.get("content-disposition") or "")
        if "filename=" in content_disposition:
            tail = content_disposition.split("filename=", 1)[-1].strip()
            filename = tail.strip('"') or filename

        return {
            "ok": True,
            "content": response.content or b"",
            "content_type": content_type,
            "filename": filename,
            "checksum": checksum,
            "status_code": response.status_code,
        }
