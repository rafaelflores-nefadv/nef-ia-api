from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.security import get_current_admin_user
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.models.operational import DjangoAiUser
from app.schemas.file import ExecutionFileListResponse, ExecutionFileMetadataResponse
from app.services.file_service import FileService

router = APIRouter(tags=["admin-execution-files"])


@router.get("/executions/{execution_id}/files", response_model=ExecutionFileListResponse)
def list_execution_files(
    execution_id: UUID,
    _: DjangoAiUser = Depends(get_current_admin_user),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> ExecutionFileListResponse:
    service = FileService(
        operational_session=operational_session,
        shared_session=shared_session,
    )
    files = service.list_execution_files(execution_id)
    return ExecutionFileListResponse(
        items=[
            ExecutionFileMetadataResponse(
                id=file.id,
                execution_id=file.execution_id,
                file_type=file.file_type,
                file_name=file.file_name,
                file_path=file.file_path,
                file_size=file.file_size,
                mime_type=file.mime_type,
                checksum=file.checksum,
                created_at=file.created_at,
            )
            for file in files
        ]
    )

