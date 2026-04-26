from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RequestFileMetadataResponse(BaseModel):
    id: UUID
    analysis_request_id: UUID
    file_name: str
    file_path: str
    file_size: int
    mime_type: str | None
    checksum: str | None
    uploaded_at: datetime


class ExecutionFileMetadataResponse(BaseModel):
    id: UUID
    execution_id: UUID
    file_type: str
    file_name: str
    file_path: str
    file_size: int
    mime_type: str | None
    checksum: str | None
    created_at: datetime


class FileUploadResponse(BaseModel):
    file: RequestFileMetadataResponse


class MultiFileUploadResponse(BaseModel):
    files: list[RequestFileMetadataResponse]


class ExecutionFileListResponse(BaseModel):
    items: list[ExecutionFileMetadataResponse]

