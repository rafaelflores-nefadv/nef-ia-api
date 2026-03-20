from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .api_client import ApiResponse, FastAPIClient


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
class AutomationRuntimeReadItem:
    automation_id: UUID
    automation_name: str
    automation_is_active: bool
    prompt_available: bool
    prompt_version: int | None
    prompt_summary: str | None
    prompt_text: str | None
    provider_slug: str | None
    model_slug: str | None
    latest_analysis_request_id: UUID | None


@dataclass
class AutomationExecutionStartItem:
    automation_id: UUID
    analysis_request_id: UUID
    request_file_id: UUID
    execution_id: UUID
    queue_job_id: UUID
    status: str
    prompt_version: int
    prompt_override_applied: bool


@dataclass
class AutomationExecutionStatusItem:
    execution_id: UUID
    analysis_request_id: UUID
    automation_id: UUID
    request_file_id: UUID | None
    request_file_name: str | None
    prompt_override_applied: bool
    status: str
    progress: int | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str
    created_at: datetime | None
    checked_at: datetime | None


@dataclass
class AutomationExecutionFileItem:
    id: UUID
    execution_id: UUID
    file_type: str
    file_name: str
    file_path: str
    file_size: int
    mime_type: str | None
    checksum: str | None
    created_at: datetime | None


class AutomationPromptsExecutionServiceError(Exception):
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


class AutomationPromptsExecutionService:
    def __init__(self, *, client: FastAPIClient | None = None) -> None:
        self.client = client or FastAPIClient()

    @staticmethod
    def _extract_error_meta(result: ApiResponse) -> tuple[str | None, str]:
        code: str | None = None
        message = str(result.error or "").strip()
        if isinstance(result.data, dict):
            error_payload = result.data.get("error")
            if isinstance(error_payload, dict):
                payload_code = str(error_payload.get("code") or "").strip()
                if payload_code:
                    code = payload_code
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
        if code == "automation_not_found":
            return "Automacao nao encontrada na FastAPI."
        if code == "prompt_not_found":
            return "Prompt oficial da automacao nao encontrado na FastAPI."
        if code == "analysis_request_not_found_for_automation":
            return (
                "Nao existe analysis_request para esta automacao no sistema compartilhado. "
                "Sem esse vinculo, nao e possivel subir arquivo e executar."
            )
        if code == "invalid_integration_token":
            return "Token de integracao FastAPI invalido."
        if code == "deactivated_integration_token":
            return "Token de integracao FastAPI desativado."
        if status_code in {401, 403}:
            return "Falha de autenticacao/permissao na FastAPI."
        if status_code == 404:
            return "Recurso nao encontrado na FastAPI."
        if status_code is None:
            return fallback_message or "Falha de comunicacao com a FastAPI."
        return fallback_message or f"Falha ao {action} na FastAPI (HTTP {status_code})."

    @staticmethod
    def _normalize_runtime_item(row: dict[str, Any]) -> AutomationRuntimeReadItem | None:
        automation_id = _to_uuid(row.get("automation_id"))
        if automation_id is None:
            return None
        return AutomationRuntimeReadItem(
            automation_id=automation_id,
            automation_name=str(row.get("automation_name") or "").strip() or str(automation_id),
            automation_is_active=bool(row.get("automation_is_active", False)),
            prompt_available=bool(row.get("prompt_available", False)),
            prompt_version=(None if row.get("prompt_version") is None else int(row.get("prompt_version"))),
            prompt_summary=str(row.get("prompt_summary") or "").strip() or None,
            prompt_text=str(row.get("prompt_text") or "").strip() or None,
            provider_slug=str(row.get("provider_slug") or "").strip() or None,
            model_slug=str(row.get("model_slug") or "").strip() or None,
            latest_analysis_request_id=_to_uuid(row.get("latest_analysis_request_id")),
        )

    @staticmethod
    def _normalize_execution_start(payload: dict[str, Any]) -> AutomationExecutionStartItem | None:
        automation_id = _to_uuid(payload.get("automation_id"))
        analysis_request_id = _to_uuid(payload.get("analysis_request_id"))
        request_file_id = _to_uuid(payload.get("request_file_id"))
        execution_id = _to_uuid(payload.get("execution_id"))
        queue_job_id = _to_uuid(payload.get("queue_job_id"))
        if (
            automation_id is None
            or analysis_request_id is None
            or request_file_id is None
            or execution_id is None
            or queue_job_id is None
        ):
            return None
        return AutomationExecutionStartItem(
            automation_id=automation_id,
            analysis_request_id=analysis_request_id,
            request_file_id=request_file_id,
            execution_id=execution_id,
            queue_job_id=queue_job_id,
            status=str(payload.get("status") or "").strip().lower() or "queued",
            prompt_version=int(payload.get("prompt_version") or 0),
            prompt_override_applied=bool(payload.get("prompt_override_applied", False)),
        )

    @staticmethod
    def _normalize_execution_status(payload: dict[str, Any]) -> AutomationExecutionStatusItem | None:
        execution_id = _to_uuid(payload.get("execution_id"))
        analysis_request_id = _to_uuid(payload.get("analysis_request_id"))
        automation_id = _to_uuid(payload.get("automation_id"))
        if execution_id is None or analysis_request_id is None or automation_id is None:
            return None
        progress_value = payload.get("progress")
        progress = None
        if progress_value is not None:
            try:
                progress = int(progress_value)
            except (TypeError, ValueError):
                progress = None
        return AutomationExecutionStatusItem(
            execution_id=execution_id,
            analysis_request_id=analysis_request_id,
            automation_id=automation_id,
            request_file_id=_to_uuid(payload.get("request_file_id")),
            request_file_name=str(payload.get("request_file_name") or "").strip() or None,
            prompt_override_applied=bool(payload.get("prompt_override_applied", False)),
            status=str(payload.get("status") or "").strip().lower() or "queued",
            progress=progress,
            started_at=_parse_dt(payload.get("started_at")),
            finished_at=_parse_dt(payload.get("finished_at")),
            error_message=str(payload.get("error_message") or "").strip(),
            created_at=_parse_dt(payload.get("created_at")),
            checked_at=_parse_dt(payload.get("checked_at")),
        )

    @staticmethod
    def _normalize_execution_file(row: dict[str, Any]) -> AutomationExecutionFileItem | None:
        file_id = _to_uuid(row.get("id"))
        execution_id = _to_uuid(row.get("execution_id"))
        if file_id is None or execution_id is None:
            return None
        file_size = 0
        try:
            file_size = int(row.get("file_size") or 0)
        except (TypeError, ValueError):
            file_size = 0
        return AutomationExecutionFileItem(
            id=file_id,
            execution_id=execution_id,
            file_type=str(row.get("file_type") or "").strip() or "-",
            file_name=str(row.get("file_name") or "").strip() or "-",
            file_path=str(row.get("file_path") or "").strip() or "-",
            file_size=file_size,
            mime_type=str(row.get("mime_type") or "").strip() or None,
            checksum=str(row.get("checksum") or "").strip() or None,
            created_at=_parse_dt(row.get("created_at")),
        )

    def list_automations_runtime(self) -> dict[str, Any]:
        result = self.client.get(
            "/api/v1/admin/automations/runtime",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        warnings: list[str] = []

        if result.is_success and isinstance(result.data, dict):
            raw_items = result.data.get("items")
            items: list[AutomationRuntimeReadItem] = []
            if isinstance(raw_items, list):
                for row in raw_items:
                    if not isinstance(row, dict):
                        continue
                    item = self._normalize_runtime_item(row)
                    if item is not None:
                        items.append(item)
            return {"source": "api", "warnings": warnings, "items": items}

        code, message = self._extract_error_meta(result)
        warnings.append(
            self._friendly_error(
                code=code,
                status_code=result.status_code,
                fallback_message=message,
                action="listar automacoes",
            )
        )
        return {"source": "unavailable", "warnings": warnings, "items": []}

    def get_automation_runtime(self, *, automation_id: UUID) -> AutomationRuntimeReadItem:
        result = self.client.get(
            f"/api/v1/admin/automations/runtime/{automation_id}",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success or not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise AutomationPromptsExecutionServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="consultar automacao",
                ),
                code=code,
                status_code=result.status_code,
            )
        item = self._normalize_runtime_item(result.data)
        if item is None:
            raise AutomationPromptsExecutionServiceError(
                "Resposta invalida da FastAPI ao consultar automacao.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        return item

    def start_execution(
        self,
        *,
        automation_id: UUID,
        uploaded_file,
        prompt_override: str | None = None,
    ) -> AutomationExecutionStartItem:
        file_name = str(getattr(uploaded_file, "name", "") or "").strip()
        if not file_name:
            raise AutomationPromptsExecutionServiceError(
                "Arquivo invalido para execucao.",
                code="invalid_uploaded_file",
                status_code=400,
            )

        content_type = str(getattr(uploaded_file, "content_type", "") or "").strip() or "application/octet-stream"
        file_content = uploaded_file.read()
        if not isinstance(file_content, (bytes, bytearray)):
            raise AutomationPromptsExecutionServiceError(
                "Falha ao ler o arquivo selecionado.",
                code="invalid_uploaded_file",
                status_code=400,
            )
        if len(file_content) <= 0:
            raise AutomationPromptsExecutionServiceError(
                "Arquivo vazio nao e permitido.",
                code="empty_uploaded_file",
                status_code=400,
            )

        result = self.client.request_multipart(
            method="POST",
            path=f"/api/v1/admin/automations/{automation_id}/executions",
            data=(
                {"prompt_override": str(prompt_override).strip()}
                if str(prompt_override or "").strip()
                else None
            ),
            files={"file": (file_name, bytes(file_content), content_type)},
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success or not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise AutomationPromptsExecutionServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="disparar execucao",
                ),
                code=code,
                status_code=result.status_code,
            )
        item = self._normalize_execution_start(result.data)
        if item is None:
            raise AutomationPromptsExecutionServiceError(
                "Resposta invalida da FastAPI ao disparar execucao.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        return item

    def get_execution_status(self, *, execution_id: UUID) -> AutomationExecutionStatusItem:
        result = self.client.get(
            f"/api/v1/admin/executions/{execution_id}/status",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success or not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise AutomationPromptsExecutionServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="consultar status da execucao",
                ),
                code=code,
                status_code=result.status_code,
            )
        item = self._normalize_execution_status(result.data)
        if item is None:
            raise AutomationPromptsExecutionServiceError(
                "Resposta invalida da FastAPI ao consultar status da execucao.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        return item

    def list_execution_files(self, *, execution_id: UUID) -> list[AutomationExecutionFileItem]:
        result = self.client.get(
            f"/api/v1/admin/executions/{execution_id}/files",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success or not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise AutomationPromptsExecutionServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="listar arquivos da execucao",
                ),
                code=code,
                status_code=result.status_code,
            )
        raw_items = result.data.get("items")
        items: list[AutomationExecutionFileItem] = []
        if isinstance(raw_items, list):
            for row in raw_items:
                if not isinstance(row, dict):
                    continue
                item = self._normalize_execution_file(row)
                if item is not None:
                    items.append(item)
        return items

    def download_execution_file(self, *, file_id: UUID) -> dict[str, Any]:
        response = self.client.request_raw(
            method="GET",
            path=f"/api/v1/admin/execution-files/{file_id}/download",
            headers=self.client.get_admin_headers(),
        )
        if not response.is_success:
            return {
                "ok": False,
                "status_code": response.status_code,
                "error": str(response.error or "Falha no download remoto do arquivo."),
            }

        headers = response.headers or {}
        content_type = str(headers.get("content-type") or "application/octet-stream")
        checksum = str(headers.get("x-file-checksum") or "").strip() or None
        filename = f"{file_id}.bin"
        content_disposition = str(headers.get("content-disposition") or "")
        if "filename=" in content_disposition:
            tail = content_disposition.split("filename=", 1)[-1].strip()
            filename = tail.strip('"') or filename

        return {
            "ok": True,
            "status_code": response.status_code,
            "content": response.content or b"",
            "content_type": content_type,
            "checksum": checksum,
            "filename": filename,
        }
