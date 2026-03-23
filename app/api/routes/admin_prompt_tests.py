import base64
import binascii
from dataclasses import asdict
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_admin_user
from app.core.exceptions import AppException
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.models.operational import DjangoAiUser
from app.repositories.operational import ApiTokenRepository
from app.schemas.admin_prompt_tests import (
    PromptTestCopyToOfficialRequest,
    PromptTestCopyToOfficialResponse,
    PromptTestDirectExecutionResponse,
    PromptTestExecutionResultResponse,
    PromptTestExecutionStartResponse,
    PromptTestExecutionStatusResponse,
)
from app.services.external_catalog_service import ExternalCatalogService
from app.services.prompt_test_async_execution_service import (
    PromptTestAsyncStartPayload,
    get_prompt_test_async_execution_service,
)
from app.services.prompt_test_engine_service import PromptTestEngineService

router = APIRouter(tags=["admin-prompt-tests"])
logger = logging.getLogger(__name__)


@router.post(
    "/prompt-tests/executions",
    response_model=PromptTestDirectExecutionResponse,
)
def execute_prompt_test_direct(
    provider_id: UUID = Form(...),
    model_id: UUID = Form(...),
    credential_id: UUID | None = Form(None),
    prompt_override: str = Form(...),
    output_type: str | None = Form(None),
    result_parser: str | None = Form(None),
    result_formatter: str | None = Form(None),
    output_schema: str | None = Form(None),
    debug_enabled: bool = Form(False),
    file: UploadFile = File(...),
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptTestDirectExecutionResponse:
    payload = PromptTestEngineService(
        operational_session=operational_session,
        shared_session=shared_session,
    ).execute(
        provider_id=str(provider_id),
        model_id=str(model_id),
        credential_id=str(credential_id) if credential_id is not None else None,
        prompt_override=prompt_override,
        output_type=output_type,
        result_parser=result_parser,
        result_formatter=result_formatter,
        output_schema=output_schema,
        debug_enabled=bool(debug_enabled),
        upload_file=file,
    )
    return PromptTestDirectExecutionResponse(**asdict(payload))


@router.post(
    "/prompt-tests/executions/start",
    response_model=PromptTestExecutionStartResponse,
)
def start_prompt_test_execution(
    provider_id: UUID = Form(...),
    model_id: UUID = Form(...),
    credential_id: UUID | None = Form(None),
    prompt_override: str = Form(...),
    output_type: str | None = Form(None),
    result_parser: str | None = Form(None),
    result_formatter: str | None = Form(None),
    output_schema: str | None = Form(None),
    debug_enabled: bool = Form(False),
    file: UploadFile = File(...),
    _: DjangoAiUser = Depends(get_current_admin_user),
) -> PromptTestExecutionStartResponse:
    file_name = str(file.filename or "").strip()
    if not file_name:
        raise AppException(
            "File name is required.",
            status_code=400,
            code="missing_file_name",
        )
    file.file.seek(0)
    upload_content = file.file.read()
    if not isinstance(upload_content, (bytes, bytearray)):
        raise AppException(
            "Uploaded file payload is invalid.",
            status_code=400,
            code="invalid_uploaded_file",
        )
    snapshot = get_prompt_test_async_execution_service().start_execution(
        payload=PromptTestAsyncStartPayload(
            provider_id=str(provider_id),
            model_id=str(model_id),
            credential_id=str(credential_id) if credential_id is not None else None,
            prompt_override=str(prompt_override or ""),
            output_type=str(output_type or "").strip() or None,
            result_parser=str(result_parser or "").strip() or None,
            result_formatter=str(result_formatter or "").strip() or None,
            output_schema=output_schema,
            debug_enabled=bool(debug_enabled),
            upload_file_name=file_name,
            upload_content=bytes(upload_content),
            upload_content_type=str(file.content_type or "").strip() or "application/octet-stream",
        )
    )
    return PromptTestExecutionStartResponse(
        execution_id=snapshot.execution_id,
        status=snapshot.status,
        phase=snapshot.phase,
        progress_percent=snapshot.progress_percent,
        status_message=snapshot.status_message,
        is_terminal=snapshot.is_terminal,
        created_at=snapshot.created_at,
    )


@router.post(
    "/prompt-tests/automations/copy-to-official",
    response_model=PromptTestCopyToOfficialResponse,
    status_code=201,
)
def copy_prompt_test_automation_to_official(
    payload: PromptTestCopyToOfficialRequest,
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptTestCopyToOfficialResponse:
    destination_token = ApiTokenRepository(operational_session).get_by_id(payload.owner_token_id)
    if destination_token is None:
        raise AppException(
            "Destination API token was not found.",
            status_code=404,
            code="owner_token_not_found",
            details={"owner_token_id": str(payload.owner_token_id)},
        )
    if not destination_token.is_active:
        raise AppException(
            "Destination API token is inactive.",
            status_code=422,
            code="owner_token_inactive",
            details={"owner_token_id": str(payload.owner_token_id)},
        )

    prompt_text = str(payload.prompt_text or "").strip()
    if not prompt_text:
        raise AppException(
            "Test automation must have a configured prompt before copy.",
            status_code=422,
            code="copy_test_automation_prompt_missing",
            details={"source_test_automation_id": str(payload.source_test_automation_id or "")},
        )

    external_service = ExternalCatalogService(
        shared_session=shared_session,
        operational_session=operational_session,
    )
    created_automation = None
    try:
        created_automation = external_service.create_automation(
            token_id=payload.owner_token_id,
            name=payload.name,
            provider_id=payload.provider_id,
            model_id=payload.model_id,
            credential_id=payload.credential_id,
            output_type=payload.output_type,
            result_parser=payload.result_parser,
            result_formatter=payload.result_formatter,
            output_schema=payload.output_schema,
            is_active=payload.is_active,
        )
        created_prompt = external_service.create_prompt(
            token_id=payload.owner_token_id,
            automation_id=created_automation.id,
            prompt_text=prompt_text,
        )
    except Exception:
        if created_automation is not None:
            try:
                external_service.delete_automation(
                    token_id=payload.owner_token_id,
                    automation_id=created_automation.id,
                )
            except Exception:
                logger.exception(
                    "Failed to rollback official automation copy after prompt copy failure.",
                    extra={
                        "owner_token_id": str(payload.owner_token_id),
                        "automation_id": str(created_automation.id),
                        "phase": "prompt_test.copy_to_official.rollback_failed",
                    },
                )
        raise

    return PromptTestCopyToOfficialResponse(
        owner_token_id=payload.owner_token_id,
        automation_id=created_automation.id,
        automation_name=created_automation.name,
        prompt_id=created_prompt.id,
        prompt_version=created_prompt.version,
        source_test_automation_id=payload.source_test_automation_id,
        source_test_prompt_id=payload.source_test_prompt_id,
    )


@router.get(
    "/prompt-tests/executions/{execution_id}/status",
    response_model=PromptTestExecutionStatusResponse,
)
def get_prompt_test_execution_status(
    execution_id: UUID,
    request: Request,
    _: DjangoAiUser = Depends(get_current_admin_user),
) -> PromptTestExecutionStatusResponse:
    snapshot = get_prompt_test_async_execution_service().get_snapshot(execution_id=execution_id)
    if snapshot is None:
        raise AppException(
            "Prompt-test execution not found.",
            status_code=404,
            code="prompt_test_execution_not_found",
            details={"execution_id": str(execution_id)},
        )
    result_url = None
    download_url = None
    debug_download_url = None
    if snapshot.result_ready:
        result_url = str(request.url_for("get_prompt_test_execution_result", execution_id=str(execution_id)))
        if snapshot.result_type == "file":
            download_url = str(request.url_for("download_prompt_test_execution_output", execution_id=str(execution_id)))
        if int(snapshot.debug_file_size or 0) > 0:
            debug_download_url = (
                f"{str(request.url_for('download_prompt_test_execution_output', execution_id=str(execution_id)))}?kind=debug"
            )
    return PromptTestExecutionStatusResponse(
        execution_id=snapshot.execution_id,
        status=snapshot.status,
        phase=snapshot.phase,
        progress_percent=snapshot.progress_percent,
        status_message=snapshot.status_message,
        is_terminal=snapshot.is_terminal,
        error_message=snapshot.error_message,
        result_ready=snapshot.result_ready,
        result_type=snapshot.result_type,
        output_file_name=snapshot.output_file_name,
        output_file_mime_type=snapshot.output_file_mime_type,
        output_file_size=snapshot.output_file_size,
        debug_file_name=snapshot.debug_file_name,
        debug_file_mime_type=snapshot.debug_file_mime_type,
        debug_file_size=snapshot.debug_file_size,
        processed_rows=snapshot.processed_rows,
        total_rows=snapshot.total_rows,
        current_row=snapshot.current_row,
        result_url=result_url,
        download_url=download_url,
        debug_download_url=debug_download_url,
        created_at=snapshot.created_at,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        updated_at=snapshot.updated_at,
    )


@router.get(
    "/prompt-tests/executions/{execution_id}/result",
    response_model=PromptTestExecutionResultResponse,
)
def get_prompt_test_execution_result(
    execution_id: UUID,
    _: DjangoAiUser = Depends(get_current_admin_user),
) -> PromptTestExecutionResultResponse:
    result = get_prompt_test_async_execution_service().get_result(execution_id=execution_id)
    if result is None:
        raise AppException(
            "Prompt-test execution result is not ready.",
            status_code=409,
            code="prompt_test_execution_result_not_ready",
            details={"execution_id": str(execution_id)},
        )
    payload = asdict(result)
    payload["execution_id"] = execution_id
    return PromptTestExecutionResultResponse(**payload)


@router.get("/prompt-tests/executions/{execution_id}/output")
def download_prompt_test_execution_output(
    execution_id: UUID,
    kind: str | None = None,
    _: DjangoAiUser = Depends(get_current_admin_user),
) -> Response:
    result = get_prompt_test_async_execution_service().get_result(execution_id=execution_id)
    if result is None:
        raise AppException(
            "Prompt-test execution result is not ready.",
            status_code=409,
            code="prompt_test_execution_result_not_ready",
            details={"execution_id": str(execution_id)},
        )
    normalized_kind = str(kind or "output").strip().lower()
    if normalized_kind not in {"output", "debug"}:
        raise AppException(
            "Prompt-test execution output kind is invalid.",
            status_code=422,
            code="prompt_test_execution_output_kind_invalid",
            details={"kind": normalized_kind},
        )
    if normalized_kind == "output" and str(result.result_type or "").strip().lower() != "file":
        raise AppException(
            "Prompt-test execution did not produce a downloadable file.",
            status_code=422,
            code="prompt_test_execution_not_file_result",
            details={"execution_id": str(execution_id)},
        )
    if normalized_kind == "debug":
        raw_base64 = str(result.debug_file_base64 or "").strip()
        file_name = str(result.debug_file_name or "").strip() or f"debug_{execution_id}.bin"
        mime_type = str(result.debug_file_mime_type or "application/octet-stream")
        checksum = str(result.debug_file_checksum or "").strip() or None
    else:
        raw_base64 = str(result.output_file_base64 or "").strip()
        file_name = str(result.output_file_name or "").strip() or f"{execution_id}.bin"
        mime_type = str(result.output_file_mime_type or "application/octet-stream")
        checksum = str(result.output_file_checksum or "").strip() or None
    if not raw_base64:
        raise AppException(
            "Prompt-test execution file payload is empty.",
            status_code=500,
            code="prompt_test_execution_output_missing",
            details={"execution_id": str(execution_id), "kind": normalized_kind},
        )
    try:
        content = base64.b64decode(raw_base64)
    except (ValueError, binascii.Error) as exc:
        raise AppException(
            "Prompt-test execution file payload is invalid.",
            status_code=500,
            code="prompt_test_execution_output_invalid",
            details={"execution_id": str(execution_id)},
        ) from exc
    headers: dict[str, str] = {}
    if checksum:
        headers["X-File-Checksum"] = checksum
    headers["Content-Disposition"] = f'attachment; filename="{file_name}"'
    return Response(
        content=content,
        media_type=mime_type,
        headers=headers,
    )
