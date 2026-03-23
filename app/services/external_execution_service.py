from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.constants import ExecutionStatus
from app.core.exceptions import AppException
from app.models.operational import DjangoAiApiToken, DjangoAiApiTokenPermission
from app.repositories.operational import (
    ExecutionFileRepository,
    ExecutionInputFileRepository,
    ExternalExecutionContextRecord,
    ExternalExecutionContextRepository,
    QueueJobRepository,
    RequestFileRepository,
)
from app.repositories.shared import SharedAnalysisRepository, SharedExecutionRepository
from app.services.execution_service import ExecutionService
from app.services.external_catalog_service import ExternalCatalogService
from app.services.file_service import DownloadableFile, FileService


@dataclass(slots=True)
class ExternalExecutionView:
    execution_id: UUID
    status: ExecutionStatus
    resource_type: Literal["prompt", "automation"]
    resource_id: UUID
    automation_id: UUID
    prompt_id: UUID | None
    analysis_request_id: UUID
    queue_job_id: UUID | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    has_files: bool | None = None
    has_structured_result: bool | None = None


@dataclass(slots=True)
class ExternalExecutionFileView:
    file_id: UUID
    execution_id: UUID
    logical_type: Literal["input", "output"]
    file_type: str
    file_name: str
    file_size: int
    mime_type: str | None
    checksum: str | None
    created_at: datetime | None


@dataclass(slots=True)
class ExternalExecutionFileResolution:
    view: ExternalExecutionFileView
    automation_id: UUID
    storage_kind: Literal["request", "execution"]


@dataclass(slots=True)
class ExternalExecutionStructuredResult:
    execution_id: UUID
    result: Any | None
    source_file_id: UUID | None = None
    source_mime_type: str | None = None


class ExternalExecutionService:
    def __init__(self, *, operational_session: Session, shared_session: Session) -> None:
        self.operational_session = operational_session
        self.shared_session = shared_session
        self.contexts = ExternalExecutionContextRepository(operational_session)
        self.queue_jobs = QueueJobRepository(operational_session)
        self.execution_files = ExecutionFileRepository(operational_session)
        self.execution_inputs = ExecutionInputFileRepository(operational_session)
        self.request_files = RequestFileRepository(operational_session)
        self.shared_analysis = SharedAnalysisRepository(shared_session)
        self.shared_executions = SharedExecutionRepository(shared_session)
        self.catalog = ExternalCatalogService(shared_session=shared_session)
        self.file_service = FileService(
            operational_session=operational_session,
            shared_session=shared_session,
        )
        self.execution_service = ExecutionService(
            operational_session=operational_session,
            shared_session=shared_session,
        )

    def execute_prompt_in_scope(
        self,
        *,
        token_id: UUID,
        api_token: DjangoAiApiToken,
        prompt_id: UUID,
        input_data: Any | None,
        upload_files: list[UploadFile] | None,
        ip_address: str | None,
        correlation_id: str | None,
    ) -> ExternalExecutionView:
        prompt = self.catalog.get_prompt_in_scope(token_id=token_id, prompt_id=prompt_id)
        if not prompt.is_active:
            raise AppException(
                "Prompt is inactive.",
                status_code=409,
                code="resource_inactive",
                details={"resource_type": "prompt", "prompt_id": str(prompt_id)},
            )
        automation = self.catalog.get_automation_in_scope(token_id=token_id, automation_id=prompt.automation_id)
        if not automation.is_active:
            raise AppException(
                "Automation is inactive.",
                status_code=409,
                code="resource_inactive",
                details={"resource_type": "automation", "automation_id": str(automation.id)},
            )
        return self._execute_in_scope(
            token_id=token_id,
            api_token=api_token,
            automation_id=automation.id,
            prompt_id=prompt.id,
            prompt_override=prompt.prompt_text,
            input_data=input_data,
            upload_files=upload_files,
            ip_address=ip_address,
            correlation_id=correlation_id,
        )

    def execute_automation_in_scope(
        self,
        *,
        token_id: UUID,
        api_token: DjangoAiApiToken,
        automation_id: UUID,
        input_data: Any | None,
        upload_files: list[UploadFile] | None,
        ip_address: str | None,
        correlation_id: str | None,
    ) -> ExternalExecutionView:
        automation = self.catalog.get_automation_in_scope(token_id=token_id, automation_id=automation_id)
        if not automation.is_active:
            raise AppException(
                "Automation is inactive.",
                status_code=409,
                code="resource_inactive",
                details={"resource_type": "automation", "automation_id": str(automation.id)},
            )
        return self._execute_in_scope(
            token_id=token_id,
            api_token=api_token,
            automation_id=automation.id,
            prompt_id=None,
            prompt_override=None,
            input_data=input_data,
            upload_files=upload_files,
            ip_address=ip_address,
            correlation_id=correlation_id,
        )

    def get_execution_in_scope(
        self,
        *,
        token_id: UUID,
        execution_id: UUID,
        resource_type: Literal["prompt", "automation"] | None = None,
        include_flags: bool = False,
    ) -> ExternalExecutionView:
        context = self._get_execution_context_in_scope(
            token_id=token_id,
            execution_id=execution_id,
            resource_type=resource_type,
        )
        return self._build_execution_view_from_context(
            context=context,
            include_flags=include_flags,
        )

    def list_executions_in_scope(
        self,
        *,
        token_id: UUID,
        resource_type: Literal["prompt", "automation"] | None = None,
        status: ExecutionStatus | None = None,
        prompt_id: UUID | None = None,
        automation_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExternalExecutionView]:
        if prompt_id is not None:
            self.catalog.get_prompt_in_scope(token_id=token_id, prompt_id=prompt_id)
        if automation_id is not None:
            self.catalog.get_automation_in_scope(token_id=token_id, automation_id=automation_id)

        apply_pagination = status is None
        contexts = self.contexts.list_by_scope(
            token_id=token_id,
            resource_type=resource_type,
            automation_id=automation_id,
            prompt_id=prompt_id,
            limit=limit if apply_pagination else None,
            offset=offset if apply_pagination else None,
        )
        if not contexts:
            return []

        selected_contexts = contexts
        if status is not None:
            execution_map = {
                item.id: item
                for item in self.shared_executions.list_by_ids([context.execution_id for context in contexts])
            }
            selected_contexts = [
                context
                for context in contexts
                if self._parse_status(
                    execution_map.get(context.execution_id).status if context.execution_id in execution_map else None
                )
                == status
            ]
            safe_offset = max(int(offset), 0)
            safe_limit = max(int(limit), 0)
            if safe_offset:
                selected_contexts = selected_contexts[safe_offset:]
            selected_contexts = selected_contexts[:safe_limit]

        return [
            self._build_execution_view_from_context(context=context)
            for context in selected_contexts
        ]

    def get_execution_files_in_scope(
        self,
        *,
        token_id: UUID,
        execution_id: UUID,
    ) -> list[ExternalExecutionFileView]:
        context = self._get_execution_context_in_scope(
            token_id=token_id,
            execution_id=execution_id,
            resource_type=None,
        )
        items: list[ExternalExecutionFileView] = []
        output_files = self.execution_files.list_by_execution_id(context.execution_id)
        for item in output_files:
            items.append(
                ExternalExecutionFileView(
                    file_id=item.id,
                    execution_id=context.execution_id,
                    logical_type="output",
                    file_type=str(item.file_type or "output"),
                    file_name=item.file_name,
                    file_size=int(item.file_size or 0),
                    mime_type=item.mime_type,
                    checksum=item.checksum,
                    created_at=item.created_at,
                )
            )

        input_links = self.execution_inputs.list_by_execution_id(context.execution_id)
        seen_request_files: set[UUID] = set()
        for link in input_links:
            if link.request_file_id in seen_request_files:
                continue
            seen_request_files.add(link.request_file_id)
            request_file = self.request_files.get_by_id(link.request_file_id)
            if request_file is None:
                continue
            items.append(
                ExternalExecutionFileView(
                    file_id=request_file.id,
                    execution_id=context.execution_id,
                    logical_type="input",
                    file_type=str(link.role or "input"),
                    file_name=request_file.file_name,
                    file_size=int(request_file.file_size or 0),
                    mime_type=request_file.mime_type,
                    checksum=request_file.checksum,
                    created_at=request_file.created_at,
                )
            )

        items.sort(
            key=lambda item: (
                item.created_at or datetime.min,
                str(item.file_id),
            ),
            reverse=True,
        )
        return items

    def get_file_in_scope(
        self,
        *,
        token_id: UUID,
        file_id: UUID,
    ) -> ExternalExecutionFileResolution:
        execution_file = self.execution_files.get_by_id(file_id)
        if execution_file is not None:
            context = self._get_execution_context_in_scope(
                token_id=token_id,
                execution_id=execution_file.execution_id,
                resource_type=None,
            )
            return ExternalExecutionFileResolution(
                view=ExternalExecutionFileView(
                    file_id=execution_file.id,
                    execution_id=execution_file.execution_id,
                    logical_type="output",
                    file_type=str(execution_file.file_type or "output"),
                    file_name=execution_file.file_name,
                    file_size=int(execution_file.file_size or 0),
                    mime_type=execution_file.mime_type,
                    checksum=execution_file.checksum,
                    created_at=execution_file.created_at,
                ),
                automation_id=context.automation_id,
                storage_kind="execution",
            )

        request_file = self.request_files.get_by_id(file_id)
        if request_file is None:
            raise AppException(
                "File not found in token scope.",
                status_code=404,
                code="file_not_found_in_scope",
                details={"file_id": str(file_id)},
            )

        input_links = self.execution_inputs.list_by_request_file_id(file_id)
        for link in input_links:
            context = self.contexts.get_by_execution_id_and_scope(
                execution_id=link.execution_id,
                token_id=token_id,
                resource_type=None,
            )
            if context is None:
                continue
            return ExternalExecutionFileResolution(
                view=ExternalExecutionFileView(
                    file_id=request_file.id,
                    execution_id=link.execution_id,
                    logical_type="input",
                    file_type=str(link.role or "input"),
                    file_name=request_file.file_name,
                    file_size=int(request_file.file_size or 0),
                    mime_type=request_file.mime_type,
                    checksum=request_file.checksum,
                    created_at=request_file.created_at,
                ),
                automation_id=context.automation_id,
                storage_kind="request",
            )

        raise AppException(
            "File not found in token scope.",
            status_code=404,
            code="file_not_found_in_scope",
            details={"file_id": str(file_id)},
        )

    def download_file_in_scope(
        self,
        *,
        token_id: UUID,
        token: DjangoAiApiToken,
        file_id: UUID,
    ) -> tuple[ExternalExecutionFileView, DownloadableFile]:
        resolved = self.get_file_in_scope(token_id=token_id, file_id=file_id)
        permissions = self._build_scoped_permissions(
            token=token,
            automation_id=resolved.automation_id,
            allow_file_upload=False,
        )
        if resolved.storage_kind == "execution":
            downloadable = self.file_service.get_execution_file_for_download(
                file_id=file_id,
                token_permissions=permissions,
            )
        else:
            downloadable = self.file_service.get_request_file_for_download(
                file_id=file_id,
                token_permissions=permissions,
            )
        return resolved.view, downloadable

    def get_execution_structured_result_in_scope(
        self,
        *,
        token_id: UUID,
        token: DjangoAiApiToken,
        execution_id: UUID,
    ) -> ExternalExecutionStructuredResult:
        context = self._get_execution_context_in_scope(
            token_id=token_id,
            execution_id=execution_id,
            resource_type=None,
        )
        output_files = [
            file_item
            for file_item in self.execution_files.list_by_execution_id(execution_id)
            if str(file_item.file_type or "").strip().lower() == "output"
        ]
        if not output_files:
            return ExternalExecutionStructuredResult(execution_id=execution_id, result=None)

        for file_item in sorted(output_files, key=lambda item: item.created_at or datetime.min, reverse=True):
            parsed = self._try_parse_structured_output_file(
                token=token,
                context=context,
                file_id=file_item.id,
                file_name=file_item.file_name,
                mime_type=file_item.mime_type,
            )
            if parsed is not None:
                return ExternalExecutionStructuredResult(
                    execution_id=execution_id,
                    result=parsed,
                    source_file_id=file_item.id,
                    source_mime_type=file_item.mime_type,
                )
        return ExternalExecutionStructuredResult(execution_id=execution_id, result=None)

    def _try_parse_structured_output_file(
        self,
        *,
        token: DjangoAiApiToken,
        context: ExternalExecutionContextRecord,
        file_id: UUID,
        file_name: str,
        mime_type: str | None,
    ) -> Any | None:
        extension = Path(str(file_name or "")).suffix.lower()
        normalized_mime = str(mime_type or "").strip().lower()
        if extension not in {".json", ".csv", ".txt"} and normalized_mime not in {
            "application/json",
            "text/csv",
            "application/csv",
            "text/plain",
        }:
            return None

        permissions = self._build_scoped_permissions(
            token=token,
            automation_id=context.automation_id,
            allow_file_upload=False,
        )
        downloadable = self.file_service.get_execution_file_for_download(
            file_id=file_id,
            token_permissions=permissions,
        )
        with open(downloadable.absolute_path, "rb") as handle:
            payload = handle.read()

        if extension == ".json" or normalized_mime == "application/json":
            try:
                return json.loads(payload.decode("utf-8"))
            except json.JSONDecodeError:
                return None
        if extension == ".csv" or normalized_mime in {"text/csv", "application/csv"}:
            text_payload = payload.decode("utf-8", errors="replace")
            reader = csv.DictReader(text_payload.splitlines())
            return [dict(item) for item in reader]

        text_payload = payload.decode("utf-8", errors="replace").strip()
        if not text_payload:
            return None
        try:
            return json.loads(text_payload)
        except json.JSONDecodeError:
            return None

    def _execute_in_scope(
        self,
        *,
        token_id: UUID,
        api_token: DjangoAiApiToken,
        automation_id: UUID,
        prompt_id: UUID | None,
        prompt_override: str | None,
        input_data: Any | None,
        upload_files: list[UploadFile] | None,
        ip_address: str | None,
        correlation_id: str | None,
    ) -> ExternalExecutionView:
        analysis_request_id = self._create_analysis_request_for_automation(automation_id=automation_id)
        permissions = self._build_scoped_permissions(
            token=api_token,
            automation_id=automation_id,
            allow_file_upload=True,
        )
        request_file_ids = self._prepare_execution_inputs(
            analysis_request_id=analysis_request_id,
            api_token=api_token,
            token_permissions=permissions,
            upload_files=upload_files,
            input_data=input_data,
            ip_address=ip_address,
        )

        try:
            created = self.execution_service.create_execution(
                analysis_request_id=analysis_request_id,
                request_file_ids=request_file_ids,
                prompt_override=prompt_override,
                api_token=api_token,
                token_permissions=permissions,
                ip_address=ip_address,
                correlation_id=correlation_id,
            )
        except AppException as exc:
            raise AppException(
                "Failed to start execution.",
                status_code=exc.status_code if exc.status_code < 500 else 500,
                code="execution_failed_to_start",
                details={"reason": exc.payload.code},
            ) from exc
        except Exception as exc:
            raise AppException(
                "Failed to start execution.",
                status_code=500,
                code="execution_failed_to_start",
            ) from exc

        context = self._create_context(
            execution_id=created.execution_id,
            token_id=token_id,
            analysis_request_id=analysis_request_id,
            resource_type="prompt" if prompt_id is not None else "automation",
            automation_id=automation_id,
            prompt_id=prompt_id,
        )
        return self._build_execution_view_from_context(
            context=context,
            fallback_status=created.status,
            fallback_queue_job_id=created.queue_job_id,
        )

    def _prepare_execution_inputs(
        self,
        *,
        analysis_request_id: UUID,
        api_token: DjangoAiApiToken,
        token_permissions: list[DjangoAiApiTokenPermission],
        upload_files: list[UploadFile] | None,
        input_data: Any | None,
        ip_address: str | None,
    ) -> list[UUID]:
        files = [item for item in (upload_files or []) if getattr(item, "filename", None)]
        if not files and input_data is None:
            raise AppException(
                "Provide at least one input file or JSON payload.",
                status_code=422,
                code="invalid_input",
            )

        request_file_ids: list[UUID] = []
        for upload_file in files:
            try:
                request_file = self.file_service.upload_request_file(
                    analysis_request_id=analysis_request_id,
                    upload_file=upload_file,
                    api_token=api_token,
                    token_permissions=token_permissions,
                    ip_address=ip_address,
                )
            except AppException as exc:
                raise AppException(
                    "Failed to upload execution input file.",
                    status_code=exc.status_code,
                    code="file_upload_failed",
                    details={"reason": exc.payload.code},
                ) from exc
            request_file_ids.append(request_file.id)

        if input_data is not None:
            try:
                payload_file = self.file_service.upload_request_json_payload(
                    analysis_request_id=analysis_request_id,
                    payload=input_data,
                    api_token=api_token,
                    token_permissions=token_permissions,
                    ip_address=ip_address,
                )
            except AppException as exc:
                raise AppException(
                    "Failed to persist JSON input payload.",
                    status_code=exc.status_code,
                    code="file_upload_failed",
                    details={"reason": exc.payload.code},
                ) from exc
            request_file_ids.append(payload_file.id)

        if not request_file_ids:
            raise AppException(
                "Provide at least one valid input file or JSON payload.",
                status_code=422,
                code="invalid_input",
            )
        return request_file_ids

    def _create_analysis_request_for_automation(self, *, automation_id: UUID) -> UUID:
        try:
            request = self.shared_analysis.create_request_for_automation(automation_id=automation_id)
            self.shared_session.commit()
            return request.id
        except Exception as exc:
            self.shared_session.rollback()
            raise AppException(
                "Failed to create analysis request.",
                status_code=500,
                code="execution_failed_to_start",
                details={"reason": "analysis_request_create_failed"},
            ) from exc

    def _create_context(
        self,
        *,
        execution_id: UUID,
        token_id: UUID,
        analysis_request_id: UUID,
        resource_type: Literal["prompt", "automation"],
        automation_id: UUID,
        prompt_id: UUID | None,
    ) -> ExternalExecutionContextRecord:
        try:
            context = self.contexts.create(
                execution_id=execution_id,
                token_id=token_id,
                analysis_request_id=analysis_request_id,
                resource_type=resource_type,
                automation_id=automation_id,
                prompt_id=prompt_id,
            )
            self.operational_session.commit()
            return context
        except Exception as exc:
            self.operational_session.rollback()
            raise AppException(
                "Failed to persist external execution context.",
                status_code=500,
                code="external_execution_context_persist_failed",
                details={"execution_id": str(execution_id), "reason": str(exc)},
            ) from exc

    def _get_execution_context_in_scope(
        self,
        *,
        token_id: UUID,
        execution_id: UUID,
        resource_type: Literal["prompt", "automation"] | None,
    ) -> ExternalExecutionContextRecord:
        context = self.contexts.get_by_execution_id_and_scope(
            execution_id=execution_id,
            token_id=token_id,
            resource_type=resource_type,
        )
        if context is None:
            raise AppException(
                "Execution not found in token scope.",
                status_code=404,
                code="execution_not_found_in_scope",
                details={"execution_id": str(execution_id)},
            )
        return context

    def _build_execution_view_from_context(
        self,
        *,
        context: ExternalExecutionContextRecord,
        fallback_status: ExecutionStatus | None = None,
        fallback_queue_job_id: UUID | None = None,
        include_flags: bool = False,
    ) -> ExternalExecutionView:
        execution = self.shared_executions.get_by_id(context.execution_id)
        if execution is None:
            if fallback_status is None:
                raise AppException(
                    "Execution not found.",
                    status_code=404,
                    code="execution_not_found",
                    details={"execution_id": str(context.execution_id)},
                )
            status_value = fallback_status
            created_at = context.created_at
        else:
            status_value = self._parse_status(execution.status)
            created_at = execution.created_at

        queue_job = self.queue_jobs.get_latest_by_execution_id(context.execution_id)
        updated_at = context.updated_at
        if queue_job is not None and queue_job.updated_at is not None:
            updated_at = queue_job.updated_at
        resource_id = context.prompt_id if context.resource_type == "prompt" and context.prompt_id is not None else context.automation_id

        has_files: bool | None = None
        has_structured_result: bool | None = None
        if include_flags:
            has_files = bool(self.execution_files.list_by_execution_id(context.execution_id))
            if not has_files:
                has_files = bool(self.execution_inputs.list_by_execution_id(context.execution_id))
            has_structured_result = self._has_structured_result_candidate(execution_id=context.execution_id)

        return ExternalExecutionView(
            execution_id=context.execution_id,
            status=status_value,
            resource_type="prompt" if context.resource_type == "prompt" else "automation",
            resource_id=resource_id,
            automation_id=context.automation_id,
            prompt_id=context.prompt_id,
            analysis_request_id=context.analysis_request_id,
            queue_job_id=queue_job.id if queue_job is not None else fallback_queue_job_id,
            started_at=queue_job.started_at if queue_job is not None else None,
            finished_at=queue_job.finished_at if queue_job is not None else None,
            error_message=queue_job.error_message if queue_job is not None else None,
            created_at=created_at,
            updated_at=updated_at,
            has_files=has_files,
            has_structured_result=has_structured_result,
        )

    def _has_structured_result_candidate(self, *, execution_id: UUID) -> bool:
        for file_item in self.execution_files.list_by_execution_id(execution_id):
            if str(file_item.file_type or "").strip().lower() != "output":
                continue
            extension = Path(str(file_item.file_name or "")).suffix.lower()
            normalized_mime = str(file_item.mime_type or "").strip().lower()
            if extension in {".json", ".csv"}:
                return True
            if normalized_mime in {"application/json", "text/csv", "application/csv"}:
                return True
        return False

    @staticmethod
    def _build_scoped_permissions(
        *,
        token: DjangoAiApiToken,
        automation_id: UUID,
        allow_file_upload: bool,
    ) -> list[DjangoAiApiTokenPermission]:
        return [
            DjangoAiApiTokenPermission(
                token_id=token.id,
                automation_id=automation_id,
                provider_id=None,
                allow_execution=True,
                allow_file_upload=allow_file_upload,
            )
        ]

    @staticmethod
    def _parse_status(raw_status: str | None) -> ExecutionStatus:
        value = str(raw_status or "").strip().lower()
        try:
            return ExecutionStatus(value)
        except ValueError:
            return ExecutionStatus.PENDING
