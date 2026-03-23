from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import ValidationError
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies.security import TokenScope, get_current_token_scope
from app.core.constants import ExecutionStatus
from app.core.exceptions import AppException
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.schemas.external_execution import (
    ExternalExecuteAutomationRequest,
    ExternalExecutePromptRequest,
    ExternalExecutionFileListResponse,
    ExternalExecutionFileResponse,
    ExternalExecutionListResponse,
    ExternalExecutionResultResponse,
    ExternalExecutionResponse,
)
from app.services.external_execution_service import ExternalExecutionService

router = APIRouter(prefix="/api/v1/external", tags=["external-executions"])


def _to_response(item) -> ExternalExecutionResponse:  # type: ignore[no-untyped-def]
    return ExternalExecutionResponse(
        id=item.execution_id,
        status=item.status,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
        automation_id=item.automation_id,
        prompt_id=item.prompt_id,
        analysis_request_id=item.analysis_request_id,
        queue_job_id=item.queue_job_id,
        started_at=item.started_at,
        finished_at=item.finished_at,
        error_message=item.error_message,
        created_at=item.created_at,
        updated_at=item.updated_at,
        has_files=item.has_files,
        has_structured_result=item.has_structured_result,
    )


def _to_file_response(item) -> ExternalExecutionFileResponse:  # type: ignore[no-untyped-def]
    return ExternalExecutionFileResponse(
        file_id=item.file_id,
        execution_id=item.execution_id,
        logical_type=item.logical_type,
        file_type=item.file_type,
        file_name=item.file_name,
        file_size=item.file_size,
        mime_type=item.mime_type,
        checksum=item.checksum,
        created_at=item.created_at,
    )


async def _parse_execute_inputs(
    request: Request,
    *,
    schema_type: type[ExternalExecutePromptRequest] | type[ExternalExecuteAutomationRequest],
) -> tuple[Any | None, list]:
    content_type = str(request.headers.get("content-type") or "").lower()
    input_data: Any | None = None
    upload_files: list = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        for _, value in form.multi_items():
            if hasattr(value, "filename") and getattr(value, "file", None) is not None:
                upload_files.append(value)

        raw_json = None
        for field_name in ("input_data", "payload", "json_payload"):
            candidate = form.get(field_name)
            if candidate is None:
                continue
            text_value = str(candidate).strip()
            if text_value:
                raw_json = text_value
                break
        if raw_json is not None:
            try:
                parsed = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                raise AppException(
                    "Invalid JSON payload in multipart request.",
                    status_code=422,
                    code="invalid_input",
                ) from exc
            try:
                payload = schema_type.model_validate({"input_data": parsed})
            except ValidationError as exc:
                raise AppException(
                    "Invalid execute payload.",
                    status_code=422,
                    code="invalid_input",
                ) from exc
            input_data = payload.input_data
    else:
        body = await request.body()
        if body:
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                raise AppException(
                    "Invalid JSON request body.",
                    status_code=422,
                    code="invalid_input",
                ) from exc
            try:
                if isinstance(parsed, dict) and "input_data" in parsed:
                    payload = schema_type.model_validate(parsed)
                elif isinstance(parsed, dict) and "payload" in parsed:
                    payload = schema_type.model_validate({"input_data": parsed.get("payload")})
                else:
                    payload = schema_type.model_validate({"input_data": parsed})
            except ValidationError as exc:
                raise AppException(
                    "Invalid execute payload.",
                    status_code=422,
                    code="invalid_input",
                ) from exc
            input_data = payload.input_data

    if not upload_files and input_data is None:
        raise AppException(
            "Provide at least one file or JSON payload.",
            status_code=422,
            code="invalid_input",
        )
    return input_data, upload_files


@router.get("/executions", response_model=ExternalExecutionListResponse)
def list_executions(
    status: ExecutionStatus | None = Query(default=None),
    resource_type: Literal["prompt", "automation"] | None = Query(default=None),
    prompt_id: UUID | None = Query(default=None),
    automation_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalExecutionListResponse:
    service = ExternalExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    items = service.list_executions_in_scope(
        token_id=token_scope.token_id,
        resource_type=resource_type,
        status=status,
        prompt_id=prompt_id,
        automation_id=automation_id,
        limit=limit,
        offset=offset,
    )
    return ExternalExecutionListResponse(items=[_to_response(item) for item in items])


@router.get("/executions/{execution_id}", response_model=ExternalExecutionResponse)
def get_execution(
    execution_id: UUID,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalExecutionResponse:
    service = ExternalExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    item = service.get_execution_in_scope(
        token_id=token_scope.token_id,
        execution_id=execution_id,
        resource_type=None,
        include_flags=True,
    )
    return _to_response(item)


@router.get("/executions/{execution_id}/files", response_model=ExternalExecutionFileListResponse)
def list_execution_files(
    execution_id: UUID,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalExecutionFileListResponse:
    service = ExternalExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    items = service.get_execution_files_in_scope(
        token_id=token_scope.token_id,
        execution_id=execution_id,
    )
    return ExternalExecutionFileListResponse(items=[_to_file_response(item) for item in items])


@router.get("/files/{file_id}", response_model=ExternalExecutionFileResponse)
def get_file_metadata(
    file_id: UUID,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalExecutionFileResponse:
    service = ExternalExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    item = service.get_file_in_scope(
        token_id=token_scope.token_id,
        file_id=file_id,
    ).view
    return _to_file_response(item)


@router.get("/files/{file_id}/download")
def download_file(
    file_id: UUID,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> FileResponse:
    service = ExternalExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    metadata, downloadable = service.download_file_in_scope(
        token_id=token_scope.token_id,
        token=token_scope.token,
        file_id=file_id,
    )
    headers: dict[str, str] = {}
    if metadata.checksum:
        headers["X-File-Checksum"] = metadata.checksum
    return FileResponse(
        downloadable.absolute_path,
        media_type=downloadable.mime_type or "application/octet-stream",
        filename=downloadable.file_name,
        headers=headers,
    )


@router.get("/executions/{execution_id}/result", response_model=ExternalExecutionResultResponse)
def get_execution_result(
    execution_id: UUID,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalExecutionResultResponse:
    service = ExternalExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    result = service.get_execution_structured_result_in_scope(
        token_id=token_scope.token_id,
        token=token_scope.token,
        execution_id=execution_id,
    )
    return ExternalExecutionResultResponse(
        execution_id=result.execution_id,
        result=result.result,
        source_file_id=result.source_file_id,
        source_mime_type=result.source_mime_type,
    )


@router.post("/prompts/{prompt_id}/execute", response_model=ExternalExecutionResponse, status_code=status.HTTP_201_CREATED)
async def execute_prompt(
    prompt_id: UUID,
    request: Request,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalExecutionResponse:
    input_data, upload_files = await _parse_execute_inputs(
        request,
        schema_type=ExternalExecutePromptRequest,
    )
    service = ExternalExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    result = service.execute_prompt_in_scope(
        token_id=token_scope.token_id,
        api_token=token_scope.token,
        prompt_id=prompt_id,
        input_data=input_data,
        upload_files=upload_files,
        ip_address=request.client.host if request.client else None,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    request.state.execution_id = result.execution_id
    return _to_response(result)


@router.get("/prompts/executions", response_model=ExternalExecutionListResponse)
def list_prompt_executions(
    status: ExecutionStatus | None = Query(default=None),
    prompt_id: UUID | None = Query(default=None),
    automation_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalExecutionListResponse:
    service = ExternalExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    items = service.list_executions_in_scope(
        token_id=token_scope.token_id,
        resource_type="prompt",
        status=status,
        prompt_id=prompt_id,
        automation_id=automation_id,
        limit=limit,
        offset=offset,
    )
    return ExternalExecutionListResponse(items=[_to_response(item) for item in items])


@router.get("/prompts/executions/{execution_id}", response_model=ExternalExecutionResponse)
def get_prompt_execution(
    execution_id: UUID,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalExecutionResponse:
    service = ExternalExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    item = service.get_execution_in_scope(
        token_id=token_scope.token_id,
        execution_id=execution_id,
        resource_type="prompt",
    )
    return _to_response(item)


@router.post("/automations/{automation_id}/execute", response_model=ExternalExecutionResponse, status_code=status.HTTP_201_CREATED)
async def execute_automation(
    automation_id: UUID,
    request: Request,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalExecutionResponse:
    input_data, upload_files = await _parse_execute_inputs(
        request,
        schema_type=ExternalExecuteAutomationRequest,
    )
    service = ExternalExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    result = service.execute_automation_in_scope(
        token_id=token_scope.token_id,
        api_token=token_scope.token,
        automation_id=automation_id,
        input_data=input_data,
        upload_files=upload_files,
        ip_address=request.client.host if request.client else None,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    request.state.execution_id = result.execution_id
    return _to_response(result)


@router.get("/automations/executions", response_model=ExternalExecutionListResponse)
def list_automation_executions(
    status: ExecutionStatus | None = Query(default=None),
    automation_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalExecutionListResponse:
    service = ExternalExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    items = service.list_executions_in_scope(
        token_id=token_scope.token_id,
        resource_type="automation",
        status=status,
        automation_id=automation_id,
        limit=limit,
        offset=offset,
    )
    return ExternalExecutionListResponse(items=[_to_response(item) for item in items])


@router.get("/automations/executions/{execution_id}", response_model=ExternalExecutionResponse)
def get_automation_execution(
    execution_id: UUID,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExternalExecutionResponse:
    service = ExternalExecutionService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    item = service.get_execution_in_scope(
        token_id=token_scope.token_id,
        execution_id=execution_id,
        resource_type="automation",
    )
    return _to_response(item)
