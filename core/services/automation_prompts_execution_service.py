from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from django.conf import settings
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
    automation_slug: str | None
    automation_is_active: bool
    owner_token_name: str | None
    is_test_automation: bool
    prompt_available: bool
    prompt_id: UUID | None
    prompt_is_active: bool | None
    prompt_version: int | None
    prompt_summary: str | None
    prompt_text: str | None
    provider_id: UUID | None
    model_id: UUID | None
    credential_id: UUID | None
    credential_name: str | None
    provider_slug: str | None
    model_slug: str | None
    output_type: str | None
    result_parser: str | None
    result_formatter: str | None
    output_schema: dict[str, Any] | str | None
    debug_enabled: bool | None
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
class ProviderReadItem:
    id: UUID
    name: str
    slug: str
    is_active: bool


@dataclass
class ProviderModelReadItem:
    id: UUID
    provider_id: UUID
    model_name: str
    model_slug: str
    is_active: bool


@dataclass
class ProviderCredentialReadItem:
    id: UUID
    provider_id: UUID
    credential_name: str
    is_active: bool


@dataclass
class OfficialOwnerTokenReadItem:
    id: UUID
    name: str
    is_active: bool


@dataclass
class PromptTestCopyToOfficialResultItem:
    owner_token_id: UUID
    automation_id: UUID
    automation_name: str
    prompt_id: UUID
    prompt_version: int
    source_test_automation_id: UUID | None
    source_test_prompt_id: int | None


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


@dataclass
class PromptTestExecutionResultItem:
    status: str
    provider_id: UUID
    provider_slug: str
    model_id: UUID
    model_slug: str
    credential_id: UUID | None
    credential_name: str
    prompt_override_applied: bool
    result_type: str
    output_text: str | None
    output_file_name: str | None
    output_file_mime_type: str | None
    output_file_base64: str | None
    output_file_checksum: str | None
    output_file_size: int
    debug_file_name: str | None
    debug_file_mime_type: str | None
    debug_file_base64: str | None
    debug_file_checksum: str | None
    debug_file_size: int
    provider_calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost: str
    duration_ms: int
    processing_summary: dict[str, Any]


@dataclass
class PromptTestExecutionStartItem:
    execution_id: UUID
    status: str
    phase: str
    progress_percent: int
    status_message: str
    is_terminal: bool
    created_at: datetime | None


@dataclass
class PromptTestExecutionStatusItem:
    execution_id: UUID
    status: str
    phase: str
    progress_percent: int
    status_message: str
    is_terminal: bool
    error_message: str
    result_ready: bool
    result_type: str | None
    output_file_name: str | None
    output_file_mime_type: str | None
    output_file_size: int
    debug_file_name: str | None
    debug_file_mime_type: str | None
    debug_file_size: int
    processed_rows: int | None
    total_rows: int | None
    current_row: int | None
    result_url: str | None
    download_url: str | None
    debug_download_url: str | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime | None


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
    def _prompt_test_timeout() -> httpx.Timeout:
        connect_timeout = float(
            getattr(
                settings,
                "FASTAPI_PROMPT_TEST_CONNECT_TIMEOUT_SECONDS",
                getattr(settings, "FASTAPI_TIMEOUT_SECONDS", 2.5),
            )
        )
        read_timeout = float(getattr(settings, "FASTAPI_PROMPT_TEST_READ_TIMEOUT_SECONDS", 240.0))
        write_timeout = float(getattr(settings, "FASTAPI_PROMPT_TEST_WRITE_TIMEOUT_SECONDS", 60.0))
        pool_timeout = float(getattr(settings, "FASTAPI_PROMPT_TEST_POOL_TIMEOUT_SECONDS", 30.0))
        return httpx.Timeout(
            connect=max(connect_timeout, 0.1),
            read=max(read_timeout, 0.1),
            write=max(write_timeout, 0.1),
            pool=max(pool_timeout, 0.1),
        )

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

    @staticmethod
    def _extract_error_details(result: ApiResponse) -> dict[str, Any] | None:
        if not isinstance(result.data, dict):
            return None
        error_payload = result.data.get("error")
        if not isinstance(error_payload, dict):
            return None
        details = error_payload.get("details")
        if isinstance(details, dict):
            return details
        return None

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
            return "Automacao nao preparada para execucao. Crie ou ajuste."
        if code == "provider_not_found":
            return "Provider nao encontrado na FastAPI."
        if code == "provider_model_not_found":
            return "Modelo nao encontrado na FastAPI."
        if code == "provider_model_mismatch":
            return "Modelo selecionado nao pertence ao provider informado."
        if code == "provider_inactive":
            return "Provider selecionado esta inativo na FastAPI."
        if code == "provider_model_inactive":
            return "Modelo selecionado esta inativo na FastAPI."
        if code == "provider_credential_not_found":
            return "Credencial nao encontrada na FastAPI."
        if code == "provider_credential_mismatch":
            return "Credencial selecionada nao pertence ao provider informado."
        if code == "provider_credential_inactive":
            return "Credencial selecionada esta inativa na FastAPI."
        if code == "automation_runtime_configuration_missing":
            return "Configuracao de runtime incompleta: provider e model sao obrigatorios."
        if code == "status_field_unavailable":
            return "Campo de status indisponivel no schema compartilhado."
        if code == "delete_blocked_by_dependencies":
            return "Exclusao bloqueada por dependencias existentes."
        if code == "owner_token_not_found":
            return "Token oficial de destino nao encontrado na FastAPI."
        if code == "owner_token_inactive":
            return "Token oficial de destino esta inativo na FastAPI."
        if code == "copy_test_automation_prompt_missing":
            return "A automacao de teste precisa ter prompt configurado para copia."
        if code == "invalid_test_automation_name":
            return "Nome invalido para criar a automacao de teste."
        if code == "invalid_test_automation_runtime":
            return "Provider/model sao obrigatorios para criar a automacao de teste."
        if code == "test_prompt_runtime_schema_incompatible":
            return "Schema de automacoes no banco compartilhado nao e compativel com criacao automatica."
        if code == "test_prompt_runtime_schema_init_failed":
            return "Falha ao inicializar tabela isolada de automacoes de teste no banco compartilhado."
        if code == "test_prompt_analysis_request_schema_incompatible":
            return "Schema de analysis_requests no banco compartilhado nao e compativel com criacao automatica."
        if code == "test_prompt_runtime_autocreate_failed":
            return "Falha ao criar automacao de teste no banco compartilhado."
        if code == "test_prompt_analysis_request_autocreate_failed":
            return "Falha ao preparar analysis_request padrao da automacao de teste."
        if code == "test_prompt_runtime_shared_automation_not_found":
            return "Automacao tecnica oficial de suporte ao prompt de teste nao foi encontrada na FastAPI."
        if code == "test_automation_not_found":
            return "Automacao de teste nao encontrada na FastAPI."
        if code == "test_automation_inactive":
            return "Automacao de teste selecionada esta inativa."
        if code == "test_automation_delete_failed":
            return "Falha ao excluir a automacao de teste na FastAPI."
        if code == "invalid_prompt_override":
            return "O prompt de teste enviado para execucao e invalido."
        if code == "execution_output_contract_invalid":
            return "Contrato de saida da automacao invalido."
        if code == "execution_output_schema_invalid":
            return "Schema de saida invalido para a automacao."
        if code == "execution_output_contract_incompatible":
            return "Contrato de saida incompativel com o tipo de arquivo de entrada."
        if code == "prompt_refinement_apply_confirmation_required":
            return "Confirmacao explicita obrigatoria para aplicar alteracoes do assistente."
        if code == "prompt_refinement_apply_empty":
            return "Selecione ao menos uma acao de apply (prompt e/ou campos de resultado)."
        if code == "prompt_refinement_manual_review_required":
            return "A API exige revisao manual antes de aplicar alteracoes estruturais."
        if code == "prompt_refinement_manual_review_confirmation_required":
            return "Confirme revisao manual para aplicar alteracoes estruturais com baixa confianca."
        if code == "prompt_refinement_schema_update_not_allowed":
            return "Atualizacao de schema fora do escopo seguro permitido para este assistente."
        if code == "prompt_refinement_reviewed_schema_out_of_scope":
            return "A revisao enviada alterou campos tecnicos fora do escopo permitido."
        if code == "prompt_refinement_field_removal_blocked":
            return "A remocao de campos foi bloqueada pela configuracao de seguranca atual."
        if code == "prompt_placeholder_unresolved":
            return "Nao foi possivel hidratar todos os placeholders obrigatorios do prompt com os dados da entrada."
        if code == "missing_file_name":
            return "O arquivo de teste precisa ter nome."
        if code == "empty_uploaded_file":
            return "Arquivo vazio nao e permitido para execucao."
        if code == "invalid_file_extension":
            return "Extensao de arquivo nao suportada para execucao."
        if code == "invalid_mime_type":
            return "Tipo de arquivo nao suportado para execucao."
        if code == "xls_legacy_not_supported":
            return "Arquivos .xls legados nao sao suportados. Converta para .xlsx."
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
        output_schema_raw = row.get("output_schema")
        output_schema: dict[str, Any] | str | None = None
        if isinstance(output_schema_raw, dict):
            output_schema = output_schema_raw
        elif output_schema_raw is not None:
            normalized_schema = str(output_schema_raw or "").strip()
            output_schema = normalized_schema or None
        return AutomationRuntimeReadItem(
            automation_id=automation_id,
            automation_name=str(row.get("automation_name") or "").strip() or str(automation_id),
            automation_slug=str(row.get("automation_slug") or "").strip() or None,
            automation_is_active=bool(row.get("automation_is_active", False)),
            owner_token_name=str(row.get("owner_token_name") or "").strip() or None,
            is_test_automation=bool(row.get("is_test_automation", False)),
            prompt_available=bool(row.get("prompt_available", False)),
            prompt_id=_to_uuid(row.get("prompt_id")),
            prompt_is_active=(
                None if row.get("prompt_is_active") is None else bool(row.get("prompt_is_active"))
            ),
            prompt_version=(None if row.get("prompt_version") is None else int(row.get("prompt_version"))),
            prompt_summary=str(row.get("prompt_summary") or "").strip() or None,
            prompt_text=str(row.get("prompt_text") or "").strip() or None,
            provider_id=_to_uuid(row.get("provider_id")),
            model_id=_to_uuid(row.get("model_id")),
            credential_id=_to_uuid(row.get("credential_id")),
            credential_name=str(row.get("credential_name") or "").strip() or None,
            provider_slug=str(row.get("provider_slug") or "").strip() or None,
            model_slug=str(row.get("model_slug") or "").strip() or None,
            output_type=str(row.get("output_type") or "").strip() or None,
            result_parser=str(row.get("result_parser") or "").strip() or None,
            result_formatter=str(row.get("result_formatter") or "").strip() or None,
            output_schema=output_schema,
            debug_enabled=(None if row.get("debug_enabled") is None else bool(row.get("debug_enabled"))),
            latest_analysis_request_id=_to_uuid(row.get("latest_analysis_request_id")),
        )

    @staticmethod
    def _normalize_provider(row: dict[str, Any]) -> ProviderReadItem | None:
        provider_id = _to_uuid(row.get("id"))
        if provider_id is None:
            return None
        return ProviderReadItem(
            id=provider_id,
            name=str(row.get("name") or "").strip() or str(provider_id),
            slug=str(row.get("slug") or "").strip().lower(),
            is_active=bool(row.get("is_active", False)),
        )

    @staticmethod
    def _normalize_provider_model(row: dict[str, Any]) -> ProviderModelReadItem | None:
        model_id = _to_uuid(row.get("id"))
        provider_id = _to_uuid(row.get("provider_id"))
        if model_id is None or provider_id is None:
            return None
        return ProviderModelReadItem(
            id=model_id,
            provider_id=provider_id,
            model_name=str(row.get("model_name") or "").strip() or str(model_id),
            model_slug=str(row.get("model_slug") or "").strip().lower(),
            is_active=bool(row.get("is_active", False)),
        )

    @staticmethod
    def _normalize_provider_credential(row: dict[str, Any]) -> ProviderCredentialReadItem | None:
        credential_id = _to_uuid(row.get("id"))
        provider_id = _to_uuid(row.get("provider_id"))
        if credential_id is None or provider_id is None:
            return None
        return ProviderCredentialReadItem(
            id=credential_id,
            provider_id=provider_id,
            credential_name=str(row.get("credential_name") or "").strip() or str(credential_id),
            is_active=bool(row.get("is_active", False)),
        )

    @staticmethod
    def _normalize_official_owner_token(row: dict[str, Any]) -> OfficialOwnerTokenReadItem | None:
        token_id = _to_uuid(row.get("id"))
        if token_id is None:
            return None
        return OfficialOwnerTokenReadItem(
            id=token_id,
            name=str(row.get("name") or "").strip() or str(token_id),
            is_active=bool(row.get("is_active", False)),
        )

    @staticmethod
    def _normalize_prompt_test_copy_to_official_result(
        row: dict[str, Any],
    ) -> PromptTestCopyToOfficialResultItem | None:
        owner_token_id = _to_uuid(row.get("owner_token_id"))
        automation_id = _to_uuid(row.get("automation_id"))
        prompt_id = _to_uuid(row.get("prompt_id"))
        if owner_token_id is None or automation_id is None or prompt_id is None:
            return None
        source_test_automation_id = _to_uuid(row.get("source_test_automation_id"))
        source_test_prompt_id_raw = row.get("source_test_prompt_id")
        source_test_prompt_id = None
        if source_test_prompt_id_raw is not None:
            try:
                source_test_prompt_id = int(source_test_prompt_id_raw)
            except (TypeError, ValueError):
                source_test_prompt_id = None
        try:
            prompt_version = int(row.get("prompt_version") or 1)
        except (TypeError, ValueError):
            prompt_version = 1
        return PromptTestCopyToOfficialResultItem(
            owner_token_id=owner_token_id,
            automation_id=automation_id,
            automation_name=str(row.get("automation_name") or "").strip() or str(automation_id),
            prompt_id=prompt_id,
            prompt_version=max(prompt_version, 1),
            source_test_automation_id=source_test_automation_id,
            source_test_prompt_id=source_test_prompt_id,
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

    @staticmethod
    def _normalize_prompt_test_execution(payload: dict[str, Any]) -> PromptTestExecutionResultItem | None:
        provider_id = _to_uuid(payload.get("provider_id"))
        model_id = _to_uuid(payload.get("model_id"))
        if provider_id is None or model_id is None:
            return None
        try:
            output_file_size = int(payload.get("output_file_size") or 0)
        except (TypeError, ValueError):
            output_file_size = 0
        try:
            debug_file_size = int(payload.get("debug_file_size") or 0)
        except (TypeError, ValueError):
            debug_file_size = 0
        try:
            provider_calls = int(payload.get("provider_calls") or 0)
        except (TypeError, ValueError):
            provider_calls = 0
        try:
            input_tokens = int(payload.get("input_tokens") or 0)
        except (TypeError, ValueError):
            input_tokens = 0
        try:
            output_tokens = int(payload.get("output_tokens") or 0)
        except (TypeError, ValueError):
            output_tokens = 0
        try:
            duration_ms = int(payload.get("duration_ms") or 0)
        except (TypeError, ValueError):
            duration_ms = 0
        processing_summary = payload.get("processing_summary")
        if not isinstance(processing_summary, dict):
            processing_summary = {}
        return PromptTestExecutionResultItem(
            status=str(payload.get("status") or "").strip().lower() or "completed",
            provider_id=provider_id,
            provider_slug=str(payload.get("provider_slug") or "").strip().lower(),
            model_id=model_id,
            model_slug=str(payload.get("model_slug") or "").strip().lower(),
            credential_id=_to_uuid(payload.get("credential_id")),
            credential_name=str(payload.get("credential_name") or "").strip(),
            prompt_override_applied=bool(payload.get("prompt_override_applied", False)),
            result_type=str(payload.get("result_type") or "").strip().lower() or "text",
            output_text=str(payload.get("output_text") or "").strip() or None,
            output_file_name=str(payload.get("output_file_name") or "").strip() or None,
            output_file_mime_type=str(payload.get("output_file_mime_type") or "").strip() or None,
            output_file_base64=str(payload.get("output_file_base64") or "").strip() or None,
            output_file_checksum=str(payload.get("output_file_checksum") or "").strip() or None,
            output_file_size=output_file_size,
            debug_file_name=str(payload.get("debug_file_name") or "").strip() or None,
            debug_file_mime_type=str(payload.get("debug_file_mime_type") or "").strip() or None,
            debug_file_base64=str(payload.get("debug_file_base64") or "").strip() or None,
            debug_file_checksum=str(payload.get("debug_file_checksum") or "").strip() or None,
            debug_file_size=debug_file_size,
            provider_calls=provider_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=str(payload.get("estimated_cost") or "0"),
            duration_ms=duration_ms,
            processing_summary=processing_summary,
        )

    @staticmethod
    def _normalize_prompt_test_execution_start(payload: dict[str, Any]) -> PromptTestExecutionStartItem | None:
        execution_id = _to_uuid(payload.get("execution_id"))
        if execution_id is None:
            return None
        try:
            progress_percent = int(payload.get("progress_percent") or 0)
        except (TypeError, ValueError):
            progress_percent = 0
        return PromptTestExecutionStartItem(
            execution_id=execution_id,
            status=str(payload.get("status") or "").strip().lower() or "queued",
            phase=str(payload.get("phase") or "").strip().lower() or "queued",
            progress_percent=max(0, min(100, progress_percent)),
            status_message=str(payload.get("status_message") or "").strip() or "Execucao iniciada.",
            is_terminal=bool(payload.get("is_terminal", False)),
            created_at=_parse_dt(payload.get("created_at")),
        )

    @staticmethod
    def _normalize_prompt_test_execution_status(payload: dict[str, Any]) -> PromptTestExecutionStatusItem | None:
        execution_id = _to_uuid(payload.get("execution_id"))
        if execution_id is None:
            return None
        try:
            progress_percent = int(payload.get("progress_percent") or 0)
        except (TypeError, ValueError):
            progress_percent = 0
        try:
            output_file_size = int(payload.get("output_file_size") or 0)
        except (TypeError, ValueError):
            output_file_size = 0
        try:
            debug_file_size = int(payload.get("debug_file_size") or 0)
        except (TypeError, ValueError):
            debug_file_size = 0
        processed_rows = None
        total_rows = None
        current_row = None
        try:
            if payload.get("processed_rows") is not None:
                processed_rows = int(payload.get("processed_rows"))
        except (TypeError, ValueError):
            processed_rows = None
        try:
            if payload.get("total_rows") is not None:
                total_rows = int(payload.get("total_rows"))
        except (TypeError, ValueError):
            total_rows = None
        try:
            if payload.get("current_row") is not None:
                current_row = int(payload.get("current_row"))
        except (TypeError, ValueError):
            current_row = None
        return PromptTestExecutionStatusItem(
            execution_id=execution_id,
            status=str(payload.get("status") or "").strip().lower() or "queued",
            phase=str(payload.get("phase") or "").strip().lower() or "queued",
            progress_percent=max(0, min(100, progress_percent)),
            status_message=str(payload.get("status_message") or "").strip() or "Execucao em andamento.",
            is_terminal=bool(payload.get("is_terminal", False)),
            error_message=str(payload.get("error_message") or "").strip(),
            result_ready=bool(payload.get("result_ready", False)),
            result_type=str(payload.get("result_type") or "").strip().lower() or None,
            output_file_name=str(payload.get("output_file_name") or "").strip() or None,
            output_file_mime_type=str(payload.get("output_file_mime_type") or "").strip() or None,
            output_file_size=output_file_size,
            debug_file_name=str(payload.get("debug_file_name") or "").strip() or None,
            debug_file_mime_type=str(payload.get("debug_file_mime_type") or "").strip() or None,
            debug_file_size=debug_file_size,
            processed_rows=processed_rows,
            total_rows=total_rows,
            current_row=current_row,
            result_url=str(payload.get("result_url") or "").strip() or None,
            download_url=str(payload.get("download_url") or "").strip() or None,
            debug_download_url=str(payload.get("debug_download_url") or "").strip() or None,
            created_at=_parse_dt(payload.get("created_at")),
            started_at=_parse_dt(payload.get("started_at")),
            finished_at=_parse_dt(payload.get("finished_at")),
            updated_at=_parse_dt(payload.get("updated_at")),
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

    def update_automation_runtime(
        self,
        *,
        automation_id: UUID,
        name: str,
        provider_id: UUID,
        model_id: UUID,
        credential_id: UUID | None,
        output_type: str | None,
        result_parser: str | None,
        result_formatter: str | None,
        output_schema: dict[str, Any] | None,
        prompt_text: str,
    ) -> AutomationRuntimeReadItem:
        payload: dict[str, Any] = {
            "name": str(name or "").strip(),
            "provider_id": str(provider_id),
            "model_id": str(model_id),
            "prompt_text": str(prompt_text or "").strip(),
        }
        payload["credential_id"] = str(credential_id) if credential_id is not None else None
        payload["output_type"] = str(output_type).strip() if str(output_type or "").strip() else None
        payload["result_parser"] = str(result_parser).strip() if str(result_parser or "").strip() else None
        payload["result_formatter"] = str(result_formatter).strip() if str(result_formatter or "").strip() else None
        payload["output_schema"] = output_schema if isinstance(output_schema, dict) else None

        result = self.client.patch(
            f"/api/v1/admin/automations/runtime/{automation_id}",
            json_body=payload,
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
                    action="atualizar automacao oficial",
                ),
                code=code,
                status_code=result.status_code,
            )
        item = self._normalize_runtime_item(result.data)
        if item is None:
            raise AutomationPromptsExecutionServiceError(
                "Resposta invalida da FastAPI ao atualizar automacao oficial.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        return item

    def set_automation_status(self, *, automation_id: UUID, is_active: bool) -> AutomationRuntimeReadItem:
        result = self.client.patch(
            f"/api/v1/admin/automations/runtime/{automation_id}/status",
            json_body={"is_active": bool(is_active)},
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
                    action="atualizar status da automacao oficial",
                ),
                code=code,
                status_code=result.status_code,
            )
        item = self._normalize_runtime_item(result.data)
        if item is None:
            raise AutomationPromptsExecutionServiceError(
                "Resposta invalida da FastAPI ao atualizar status da automacao oficial.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        return item

    def delete_automation(self, *, automation_id: UUID) -> None:
        result = self.client.delete(
            f"/api/v1/admin/automations/runtime/{automation_id}",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if result.status_code == 204:
            return
        if result.is_success:
            return
        code, message = self._extract_error_meta(result)
        raise AutomationPromptsExecutionServiceError(
            self._friendly_error(
                code=code,
                status_code=result.status_code,
                fallback_message=message,
                action="excluir automacao oficial",
            ),
            code=code,
            status_code=result.status_code,
        )

    def list_providers(self) -> list[ProviderReadItem]:
        result = self.client.get(
            "/api/v1/admin/providers",
            headers=self.client.get_admin_headers(),
            expect_dict=False,
        )
        if not result.is_success or not isinstance(result.data, list):
            code, message = self._extract_error_meta(result)
            raise AutomationPromptsExecutionServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="listar providers",
                ),
                code=code,
                status_code=result.status_code,
            )
        items: list[ProviderReadItem] = []
        for row in result.data:
            if not isinstance(row, dict):
                continue
            normalized = self._normalize_provider(row)
            if normalized is not None and normalized.is_active:
                items.append(normalized)
        items.sort(key=lambda item: item.name.lower())
        return items

    def list_provider_models(self, *, provider_id: UUID) -> list[ProviderModelReadItem]:
        result = self.client.get(
            f"/api/v1/admin/providers/{provider_id}/models",
            headers=self.client.get_admin_headers(),
            expect_dict=False,
        )
        if not result.is_success or not isinstance(result.data, list):
            code, message = self._extract_error_meta(result)
            raise AutomationPromptsExecutionServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="listar modelos do provider",
                ),
                code=code,
                status_code=result.status_code,
            )
        items: list[ProviderModelReadItem] = []
        for row in result.data:
            if not isinstance(row, dict):
                continue
            normalized = self._normalize_provider_model(row)
            if normalized is not None and normalized.is_active:
                items.append(normalized)
        items.sort(key=lambda item: item.model_name.lower())
        return items

    def list_provider_credentials(self, *, provider_id: UUID) -> list[ProviderCredentialReadItem]:
        result = self.client.get(
            f"/api/v1/admin/providers/{provider_id}/credentials",
            headers=self.client.get_admin_headers(),
            expect_dict=False,
        )
        if not result.is_success or not isinstance(result.data, list):
            code, message = self._extract_error_meta(result)
            raise AutomationPromptsExecutionServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="listar credenciais do provider",
                ),
                code=code,
                status_code=result.status_code,
            )
        items: list[ProviderCredentialReadItem] = []
        for row in result.data:
            if not isinstance(row, dict):
                continue
            normalized = self._normalize_provider_credential(row)
            if normalized is not None and normalized.is_active:
                items.append(normalized)
        items.sort(key=lambda item: item.credential_name.lower())
        return items

    def list_official_owner_tokens(self) -> list[OfficialOwnerTokenReadItem]:
        result = self.client.get(
            "/api/v1/admin/tokens",
            headers=self.client.get_admin_headers(),
            expect_dict=False,
        )
        if not result.is_success or not isinstance(result.data, list):
            code, message = self._extract_error_meta(result)
            raise AutomationPromptsExecutionServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="listar tokens oficiais",
                ),
                code=code,
                status_code=result.status_code,
            )
        items: list[OfficialOwnerTokenReadItem] = []
        for row in result.data:
            if not isinstance(row, dict):
                continue
            normalized = self._normalize_official_owner_token(row)
            if normalized is not None and normalized.is_active:
                items.append(normalized)
        items.sort(key=lambda item: item.name.lower())
        return items

    def prompt_refinement_preview(
        self,
        *,
        automation_id: UUID,
        raw_prompt: str,
        expected_result_description: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "automation_id": str(automation_id),
            "raw_prompt": str(raw_prompt or "").strip(),
        }
        if str(expected_result_description or "").strip():
            payload["expected_result_description"] = str(expected_result_description).strip()
        return self._post_external_assistant(
            path="/api/v1/external/assistants/prompt-refinement/preview",
            payload=payload,
            action="analisar prompt (modo simples)",
        )

    def prompt_refinement_apply(
        self,
        *,
        automation_id: UUID,
        corrected_prompt: str | None,
        apply_prompt_update: bool,
        apply_schema_update: bool,
        proposed_output_schema: dict[str, Any] | None,
        create_new_prompt_version: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "automation_id": str(automation_id),
            "apply_prompt_update": bool(apply_prompt_update),
            "apply_schema_update": bool(apply_schema_update),
            "create_new_prompt_version": bool(create_new_prompt_version),
            "confirm_apply": True,
        }
        normalized_prompt = str(corrected_prompt or "").strip()
        if normalized_prompt:
            payload["corrected_prompt"] = normalized_prompt
        if isinstance(proposed_output_schema, dict):
            payload["proposed_output_schema"] = proposed_output_schema
        return self._post_external_assistant(
            path="/api/v1/external/assistants/prompt-refinement/apply",
            payload=payload,
            action="aplicar ajustes do assistente (modo simples)",
        )

    def prompt_refinement_advanced_preview(
        self,
        *,
        automation_id: UUID,
        raw_prompt: str,
        expected_result_description: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "automation_id": str(automation_id),
            "raw_prompt": str(raw_prompt or "").strip(),
        }
        if str(expected_result_description or "").strip():
            payload["expected_result_description"] = str(expected_result_description).strip()
        return self._post_external_assistant(
            path="/api/v1/external/assistants/prompt-refinement/advanced-preview",
            payload=payload,
            action="analisar prompt (modo avancado)",
        )

    def prompt_refinement_advanced_apply(
        self,
        *,
        automation_id: UUID,
        corrected_prompt: str | None,
        expected_result_description: str | None,
        apply_prompt_update: bool,
        apply_schema_update: bool,
        reviewed_output_schema: dict[str, Any] | None,
        create_new_prompt_version: bool = False,
        confirm_manual_review: bool = False,
        allow_field_removals: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "automation_id": str(automation_id),
            "apply_prompt_update": bool(apply_prompt_update),
            "apply_schema_update": bool(apply_schema_update),
            "create_new_prompt_version": bool(create_new_prompt_version),
            "confirm_apply": True,
            "confirm_manual_review": bool(confirm_manual_review),
            "allow_field_removals": bool(allow_field_removals),
        }
        normalized_prompt = str(corrected_prompt or "").strip()
        if normalized_prompt:
            payload["corrected_prompt"] = normalized_prompt
        normalized_expected = str(expected_result_description or "").strip()
        if normalized_expected:
            payload["expected_result_description"] = normalized_expected
        if isinstance(reviewed_output_schema, dict):
            payload["reviewed_output_schema"] = reviewed_output_schema
        return self._post_external_assistant(
            path="/api/v1/external/assistants/prompt-refinement/advanced-apply",
            payload=payload,
            action="aplicar ajustes do assistente (modo avancado)",
        )

    def _post_external_assistant(
        self,
        *,
        path: str,
        payload: dict[str, Any],
        action: str,
    ) -> dict[str, Any]:
        result = self.client.post(
            path,
            json_body=payload,
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
                    action=action,
                ),
                code=code,
                status_code=result.status_code,
            )
        return result.data

    def copy_test_automation_to_official(
        self,
        *,
        owner_token_id: UUID,
        name: str,
        provider_id: UUID,
        model_id: UUID,
        credential_id: UUID | None,
        output_type: str | None,
        result_parser: str | None,
        result_formatter: str | None,
        output_schema: dict[str, Any] | None,
        is_active: bool,
        prompt_text: str,
        source_test_automation_id: UUID | None = None,
        source_test_prompt_id: int | None = None,
    ) -> PromptTestCopyToOfficialResultItem:
        payload: dict[str, Any] = {
            "owner_token_id": str(owner_token_id),
            "name": str(name or "").strip(),
            "provider_id": str(provider_id),
            "model_id": str(model_id),
            "is_active": bool(is_active),
            "prompt_text": str(prompt_text or "").strip(),
        }
        if credential_id is not None:
            payload["credential_id"] = str(credential_id)
        if str(output_type or "").strip():
            payload["output_type"] = str(output_type).strip()
        if str(result_parser or "").strip():
            payload["result_parser"] = str(result_parser).strip()
        if str(result_formatter or "").strip():
            payload["result_formatter"] = str(result_formatter).strip()
        if isinstance(output_schema, dict):
            payload["output_schema"] = output_schema
        if source_test_automation_id is not None:
            payload["source_test_automation_id"] = str(source_test_automation_id)
        if source_test_prompt_id is not None:
            payload["source_test_prompt_id"] = int(source_test_prompt_id)

        result = self.client.post(
            "/api/v1/admin/prompt-tests/automations/copy-to-official",
            json_body=payload,
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
                    action="copiar automacao de teste para oficial",
                ),
                code=code,
                status_code=result.status_code,
            )
        item = self._normalize_prompt_test_copy_to_official_result(result.data)
        if item is None:
            raise AutomationPromptsExecutionServiceError(
                "Resposta invalida da FastAPI ao copiar automacao de teste para oficial.",
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
        file_name, file_content, content_type = self._read_uploaded_file_payload(uploaded_file)
        return self._start_execution_request(
            path=f"/api/v1/admin/automations/{automation_id}/executions",
            file_name=file_name,
            file_content=file_content,
            content_type=content_type,
            prompt_override=prompt_override,
        )

    def execute_test_prompt(
        self,
        *,
        provider_id: UUID,
        model_id: UUID,
        credential_id: UUID | None,
        uploaded_file,
        prompt_override: str,
        output_type: str | None = None,
        result_parser: str | None = None,
        result_formatter: str | None = None,
        output_schema: dict[str, Any] | None = None,
        debug_enabled: bool = False,
    ) -> PromptTestExecutionResultItem:
        file_name, file_content, content_type = self._read_uploaded_file_payload(uploaded_file)
        data: dict[str, Any] = {
            "provider_id": str(provider_id),
            "model_id": str(model_id),
            "prompt_override": str(prompt_override or "").strip(),
        }
        if credential_id is not None:
            data["credential_id"] = str(credential_id)
        if str(output_type or "").strip():
            data["output_type"] = str(output_type).strip()
        if str(result_parser or "").strip():
            data["result_parser"] = str(result_parser).strip()
        if str(result_formatter or "").strip():
            data["result_formatter"] = str(result_formatter).strip()
        if isinstance(output_schema, dict) and output_schema:
            data["output_schema"] = json.dumps(output_schema, ensure_ascii=False)
        if debug_enabled:
            data["debug_enabled"] = "true"
        result = self.client.request_multipart(
            method="POST",
            path="/api/v1/admin/prompt-tests/executions",
            data=data,
            files={"file": (file_name, file_content, content_type)},
            headers=self.client.get_admin_headers(),
            expect_dict=True,
            timeout=self._prompt_test_timeout(),
        )
        if not result.is_success or not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise AutomationPromptsExecutionServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="executar prompt de teste",
                ),
                code=code,
                status_code=result.status_code,
            )
        item = self._normalize_prompt_test_execution(result.data)
        if item is None:
            raise AutomationPromptsExecutionServiceError(
                "Resposta invalida da FastAPI ao executar prompt de teste.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        return item

    def start_test_prompt_execution(
        self,
        *,
        provider_id: UUID,
        model_id: UUID,
        credential_id: UUID | None,
        uploaded_file,
        prompt_override: str,
        output_type: str | None = None,
        result_parser: str | None = None,
        result_formatter: str | None = None,
        output_schema: dict[str, Any] | None = None,
        debug_enabled: bool = False,
    ) -> PromptTestExecutionStartItem:
        file_name, file_content, content_type = self._read_uploaded_file_payload(uploaded_file)
        data: dict[str, Any] = {
            "provider_id": str(provider_id),
            "model_id": str(model_id),
            "prompt_override": str(prompt_override or "").strip(),
        }
        if credential_id is not None:
            data["credential_id"] = str(credential_id)
        if str(output_type or "").strip():
            data["output_type"] = str(output_type).strip()
        if str(result_parser or "").strip():
            data["result_parser"] = str(result_parser).strip()
        if str(result_formatter or "").strip():
            data["result_formatter"] = str(result_formatter).strip()
        if isinstance(output_schema, dict) and output_schema:
            data["output_schema"] = json.dumps(output_schema, ensure_ascii=False)
        if debug_enabled:
            data["debug_enabled"] = "true"
        result = self.client.request_multipart(
            method="POST",
            path="/api/v1/admin/prompt-tests/executions/start",
            data=data,
            files={"file": (file_name, file_content, content_type)},
            headers=self.client.get_admin_headers(),
            expect_dict=True,
            timeout=self._prompt_test_timeout(),
        )
        if not result.is_success or not isinstance(result.data, dict):
            code, message = self._extract_error_meta(result)
            raise AutomationPromptsExecutionServiceError(
                self._friendly_error(
                    code=code,
                    status_code=result.status_code,
                    fallback_message=message,
                    action="iniciar execucao de prompt de teste",
                ),
                code=code,
                status_code=result.status_code,
            )
        item = self._normalize_prompt_test_execution_start(result.data)
        if item is None:
            raise AutomationPromptsExecutionServiceError(
                "Resposta invalida da FastAPI ao iniciar execucao de prompt de teste.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        return item

    def get_test_prompt_execution_status(self, *, execution_id: UUID) -> PromptTestExecutionStatusItem:
        result = self.client.get(
            f"/api/v1/admin/prompt-tests/executions/{execution_id}/status",
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
                    action="consultar status da execucao de prompt de teste",
                ),
                code=code,
                status_code=result.status_code,
            )
        item = self._normalize_prompt_test_execution_status(result.data)
        if item is None:
            raise AutomationPromptsExecutionServiceError(
                "Resposta invalida da FastAPI ao consultar status da execucao de prompt de teste.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        return item

    def get_test_prompt_execution_result(self, *, execution_id: UUID) -> PromptTestExecutionResultItem:
        result = self.client.get(
            f"/api/v1/admin/prompt-tests/executions/{execution_id}/result",
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
                    action="obter resultado da execucao de prompt de teste",
                ),
                code=code,
                status_code=result.status_code,
            )
        item = self._normalize_prompt_test_execution(result.data)
        if item is None:
            raise AutomationPromptsExecutionServiceError(
                "Resposta invalida da FastAPI ao obter resultado da execucao de prompt de teste.",
                code="fastapi_invalid_response",
                status_code=result.status_code,
            )
        return item

    def _read_uploaded_file_payload(self, uploaded_file) -> tuple[str, bytes, str]:
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
        return file_name, bytes(file_content), content_type

    def _start_execution_request(
        self,
        *,
        path: str,
        file_name: str,
        file_content: bytes,
        content_type: str,
        prompt_override: str | None,
    ) -> AutomationExecutionStartItem:
        result = self.client.request_multipart(
            method="POST",
            path=path,
            data=(
                {"prompt_override": str(prompt_override).strip()}
                if str(prompt_override or "").strip()
                else None
            ),
            files={"file": (file_name, file_content, content_type)},
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
