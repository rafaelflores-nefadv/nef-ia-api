from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_token
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.models.operational import DjangoAiApiToken
from app.schemas.file import FileUploadResponse, RequestFileMetadataResponse
from app.services.file_service import FileService

router = APIRouter(prefix="/api/v1/files", tags=["files"])


@router.post("/request-upload", response_model=FileUploadResponse)
def upload_request_file(
    request: Request,
    analysis_request_id: UUID = Form(...),
    file: UploadFile = File(...),
    api_token: DjangoAiApiToken = Depends(get_current_token),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> FileUploadResponse:
    token_permissions = getattr(request.state, "token_permissions", [])
    ip_address = request.client.host if request.client else None

    service = FileService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    request_file = service.upload_request_file(
        analysis_request_id=analysis_request_id,
        upload_file=file,
        api_token=api_token,
        token_permissions=token_permissions,
        ip_address=ip_address,
    )
    return FileUploadResponse(
        file=RequestFileMetadataResponse(
            id=request_file.id,
            analysis_request_id=request_file.analysis_request_id,
            file_name=request_file.file_name,
            file_path=request_file.file_path,
            file_size=request_file.file_size,
            mime_type=request_file.mime_type,
            checksum=request_file.checksum,
            uploaded_at=request_file.uploaded_at,
        )
    )


@router.get("/request-files/{file_id}/download")
def download_request_file(
    file_id: UUID,
    request: Request,
    _: DjangoAiApiToken = Depends(get_current_token),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> FileResponse:
    token_permissions = getattr(request.state, "token_permissions", [])
    service = FileService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    downloadable = service.get_request_file_for_download(
        file_id=file_id,
        token_permissions=token_permissions,
    )
    headers = {}
    if downloadable.checksum:
        headers["X-File-Checksum"] = downloadable.checksum
    return FileResponse(
        downloadable.absolute_path,
        media_type=downloadable.mime_type or "application/octet-stream",
        filename=downloadable.file_name,
        headers=headers,
    )


@router.get("/execution-files/{file_id}/download")
def download_execution_file(
    file_id: UUID,
    request: Request,
    _: DjangoAiApiToken = Depends(get_current_token),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> FileResponse:
    token_permissions = getattr(request.state, "token_permissions", [])
    service = FileService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    downloadable = service.get_execution_file_for_download(
        file_id=file_id,
        token_permissions=token_permissions,
    )
    headers = {}
    if downloadable.checksum:
        headers["X-File-Checksum"] = downloadable.checksum
    return FileResponse(
        downloadable.absolute_path,
        media_type=downloadable.mime_type or "application/octet-stream",
        filename=downloadable.file_name,
        headers=headers,
    )

