import logging
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, BinaryIO
from uuid import UUID

from fastapi import UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.integrations.storage import LocalStorageProvider, StorageProvider
from app.integrations.storage.base import StoredFile
from app.models.operational import (
    DjangoAiApiToken,
    DjangoAiApiTokenPermission,
    DjangoAiAuditLog,
    DjangoAiExecutionFile,
    DjangoAiRequestFile,
)
from app.repositories.operational import AuditLogRepository, ExecutionFileRepository, RequestFileRepository
from app.repositories.shared import SharedAnalysisRepository
from app.services.token_service import check_token_permission

logger = logging.getLogger(__name__)
settings = get_settings()

ALLOWED_EXECUTION_FILE_TYPES = {"output", "error", "debug", "intermediate"}
LEGACY_XLS_EXTENSION = ".xls"


@dataclass(slots=True)
class DownloadableFile:
    absolute_path: str
    file_name: str
    mime_type: str | None
    checksum: str | None


class FileService:
    def __init__(
        self,
        *,
        operational_session: Session,
        shared_session: Session,
        storage: StorageProvider | None = None,
    ) -> None:
        self.operational_session = operational_session
        self.shared_session = shared_session
        self.request_files = RequestFileRepository(operational_session)
        self.execution_files = ExecutionFileRepository(operational_session)
        self.shared_analysis = SharedAnalysisRepository(shared_session)
        self.audit_logs = AuditLogRepository(operational_session)
        self.storage = storage or LocalStorageProvider(
            root_path=settings.storage_path,
            chunk_size_bytes=settings.upload_chunk_size_bytes,
        )
        self.max_size_bytes = settings.max_upload_size_mb * 1024 * 1024
        self.allowed_extensions = {extension.lower() for extension in settings.allowed_file_extensions}
        self.allowed_mimes = {mime.lower() for mime in settings.allowed_file_mime_types}

    def _validate_upload_file(self, upload_file: UploadFile) -> None:
        if not upload_file.filename:
            raise AppException("File name is required.", status_code=400, code="missing_file_name")

        extension = ("." + upload_file.filename.rsplit(".", 1)[-1].lower()) if "." in upload_file.filename else ""
        if extension == LEGACY_XLS_EXTENSION:
            raise AppException(
                "Legacy .xls files are not supported. Convert the file to .xlsx before upload.",
                status_code=422,
                code="xls_legacy_not_supported",
            )
        if extension not in self.allowed_extensions:
            raise AppException(
                "Unsupported file extension.",
                status_code=400,
                code="invalid_file_extension",
                details={"allowed_extensions": sorted(self.allowed_extensions)},
            )

        mime_type = (upload_file.content_type or "").lower()
        if mime_type and mime_type not in self.allowed_mimes:
            raise AppException(
                "Unsupported MIME type.",
                status_code=400,
                code="invalid_mime_type",
                details={"allowed_mime_types": sorted(self.allowed_mimes)},
            )

    def upload_request_file(
        self,
        *,
        analysis_request_id: UUID,
        upload_file: UploadFile,
        api_token: DjangoAiApiToken,
        token_permissions: list[DjangoAiApiTokenPermission],
        ip_address: str | None = None,
    ) -> DjangoAiRequestFile:
        logger.info(
            "Request file upload started.",
            extra={"analysis_request_id": str(analysis_request_id), "token_id": str(api_token.id)},
        )
        self._validate_upload_file(upload_file)
        self._get_scoped_analysis_request_for_upload(
            analysis_request_id=analysis_request_id,
            token_permissions=token_permissions,
        )

        stored: StoredFile | None = None
        try:
            stored = self.storage.save_uploaded_file(
                upload_file=upload_file,
                category="requests",
                entity_id=analysis_request_id,
                max_size_bytes=self.max_size_bytes,
            )
            if stored.file_size <= 0:
                self.storage.delete_file(stored.relative_path)
                raise AppException(
                    "Uploaded file is empty.",
                    status_code=400,
                    code="empty_file",
                )
        except ValueError as exc:
            raise AppException(
                "Uploaded file exceeds configured maximum size.",
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                code="file_too_large",
                details={"max_size_mb": settings.max_upload_size_mb},
            ) from exc

        return self._persist_request_file_record(
            analysis_request_id=analysis_request_id,
            stored=stored,
            api_token=api_token,
            ip_address=ip_address,
        )

    def upload_request_json_payload(
        self,
        *,
        analysis_request_id: UUID,
        payload: Any,
        api_token: DjangoAiApiToken,
        token_permissions: list[DjangoAiApiTokenPermission],
        ip_address: str | None = None,
        file_name: str = "input_payload.json",
    ) -> DjangoAiRequestFile:
        self._get_scoped_analysis_request_for_upload(
            analysis_request_id=analysis_request_id,
            token_permissions=token_permissions,
        )

        try:
            serialized = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise AppException(
                "JSON payload is not serializable.",
                status_code=422,
                code="invalid_input",
            ) from exc

        payload_bytes = serialized.encode("utf-8")
        if len(payload_bytes) > self.max_size_bytes:
            raise AppException(
                "JSON payload exceeds configured maximum size.",
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                code="file_too_large",
                details={"max_size_mb": settings.max_upload_size_mb},
            )

        stored = self.storage.save_generated_file(
            content=payload_bytes,
            category="requests",
            entity_id=analysis_request_id,
            subdir="json",
            file_name=file_name,
            mime_type="application/json",
        )
        return self._persist_request_file_record(
            analysis_request_id=analysis_request_id,
            stored=stored,
            api_token=api_token,
            ip_address=ip_address,
        )

    def _persist_request_file_record(
        self,
        *,
        analysis_request_id: UUID,
        stored: StoredFile,
        api_token: DjangoAiApiToken,
        ip_address: str | None,
    ) -> DjangoAiRequestFile:
        try:
            request_file = DjangoAiRequestFile(
                analysis_request_id=analysis_request_id,
                file_name=stored.file_name,
                file_path=stored.relative_path,
                file_size=stored.file_size,
                mime_type=stored.mime_type,
                checksum=stored.checksum,
                uploaded_at=datetime.now(timezone.utc),
            )
            self.request_files.add(request_file)
            self.audit_logs.add(
                DjangoAiAuditLog(
                    action_type="request_file_uploaded",
                    entity_type="django_ai_request_files",
                    entity_id=str(request_file.id),
                    performed_by_user_id=None,
                    changes_json={
                        "analysis_request_id": str(analysis_request_id),
                        "token_id": str(api_token.id),
                        "file_size": stored.file_size,
                    },
                    ip_address=ip_address,
                )
            )
            self.operational_session.commit()
            self.operational_session.refresh(request_file)
            logger.info(
                "Request file upload completed.",
                extra={
                    "file_id": str(request_file.id),
                    "analysis_request_id": str(analysis_request_id),
                    "file_size": request_file.file_size,
                },
            )
            return request_file
        except Exception as exc:
            self.operational_session.rollback()
            if stored is not None:
                self.storage.delete_file(stored.relative_path)
            logger.exception("Request file upload failed.", exc_info=exc)
            if isinstance(exc, AppException):
                raise
            raise AppException("Failed to persist uploaded file metadata.", status_code=500, code="file_persist_failed") from exc

    def _get_scoped_analysis_request_for_upload(
        self,
        *,
        analysis_request_id: UUID,
        token_permissions: list[DjangoAiApiTokenPermission],
    ) -> None:
        shared_request = self.shared_analysis.get_request_by_id(analysis_request_id)
        if shared_request is None:
            raise AppException(
                "analysis_request_id not found in shared system.",
                status_code=404,
                code="analysis_request_not_found",
                details={"analysis_request_id": str(analysis_request_id)},
            )

        has_permission = check_token_permission(
            permissions=token_permissions,
            operation="file_upload",
            automation_id=shared_request.automation_id,
        )
        if not has_permission:
            raise AppException(
                "Token does not allow file upload for this automation.",
                status_code=403,
                code="file_upload_permission_denied",
            )

    def register_generated_execution_file(
        self,
        *,
        execution_id: UUID,
        file_type: str,
        file_name: str,
        content: bytes | BinaryIO,
        mime_type: str | None = None,
        ip_address: str | None = None,
    ) -> DjangoAiExecutionFile:
        if file_type not in ALLOWED_EXECUTION_FILE_TYPES:
            raise AppException(
                "Invalid execution file type.",
                status_code=400,
                code="invalid_execution_file_type",
                details={"allowed_types": sorted(ALLOWED_EXECUTION_FILE_TYPES)},
            )

        shared_execution = self.shared_analysis.get_execution_by_id(execution_id)
        if shared_execution is None:
            raise AppException(
                "analysis_execution_id not found in shared system.",
                status_code=404,
                code="analysis_execution_not_found",
                details={"execution_id": str(execution_id)},
            )

        stored = self.storage.save_generated_file(
            content=content,
            category="executions",
            entity_id=execution_id,
            subdir=file_type,
            file_name=file_name,
        )

        execution_file = DjangoAiExecutionFile(
            execution_id=execution_id,
            file_type=file_type,
            file_name=stored.file_name,
            file_path=stored.relative_path,
            file_size=stored.file_size,
            mime_type=mime_type,
            checksum=stored.checksum,
        )
        self.execution_files.add(execution_file)
        self.audit_logs.add(
            DjangoAiAuditLog(
                action_type="execution_file_registered",
                entity_type="django_ai_execution_files",
                entity_id=str(execution_file.id),
                performed_by_user_id=None,
                changes_json={
                    "execution_id": str(execution_id),
                    "file_type": file_type,
                    "file_size": stored.file_size,
                },
                ip_address=ip_address,
            )
        )
        self.operational_session.commit()
        self.operational_session.refresh(execution_file)
        return execution_file

    def _assert_storage_consistency(self, *, file_path: str, expected_size: int | None = None) -> str:
        metadata = self.storage.get_file_metadata(file_path)
        if not metadata.exists:
            logger.warning("File missing in storage.", extra={"file_path": file_path})
            raise AppException(
                "File metadata exists in database but physical file is missing in storage.",
                status_code=404,
                code="file_missing_in_storage",
            )

        if expected_size is not None and metadata.file_size is not None and metadata.file_size != expected_size:
            logger.error(
                "File size mismatch between DB and storage.",
                extra={"file_path": file_path, "expected_size": expected_size, "storage_size": metadata.file_size},
            )
            raise AppException(
                "File metadata is inconsistent between database and storage.",
                status_code=409,
                code="file_storage_mismatch",
            )
        return str(metadata.absolute_path)

    def get_request_file_for_download(
        self,
        *,
        file_id: UUID,
        token_permissions: list[DjangoAiApiTokenPermission],
    ) -> DownloadableFile:
        logger.info("Request file download initiated.", extra={"file_id": str(file_id)})
        request_file = self.request_files.get_by_id(file_id)
        if request_file is None:
            raise AppException("Request file not found.", status_code=404, code="request_file_not_found")

        shared_request = self.shared_analysis.get_request_by_id(request_file.analysis_request_id)
        if shared_request is None:
            raise AppException("Related analysis request not found.", status_code=404, code="analysis_request_not_found")

        allowed = check_token_permission(
            permissions=token_permissions,
            operation="file_download",
            automation_id=shared_request.automation_id,
        )
        if not allowed:
            raise AppException("Token cannot download this request file.", status_code=403, code="file_download_permission_denied")

        absolute_path = self._assert_storage_consistency(file_path=request_file.file_path, expected_size=request_file.file_size)
        return DownloadableFile(
            absolute_path=absolute_path,
            file_name=request_file.file_name,
            mime_type=request_file.mime_type,
            checksum=request_file.checksum,
        )

    def get_execution_file_for_download(
        self,
        *,
        file_id: UUID,
        token_permissions: list[DjangoAiApiTokenPermission],
    ) -> DownloadableFile:
        logger.info("Execution file download initiated.", extra={"file_id": str(file_id)})
        execution_file = self.execution_files.get_by_id(file_id)
        if execution_file is None:
            raise AppException("Execution file not found.", status_code=404, code="execution_file_not_found")

        shared_execution = self.shared_analysis.get_execution_by_id(execution_file.execution_id)
        if shared_execution is None:
            raise AppException("Related execution not found.", status_code=404, code="analysis_execution_not_found")
        shared_request = self.shared_analysis.get_request_by_id(shared_execution.analysis_request_id)
        if shared_request is None:
            raise AppException("Related analysis request not found.", status_code=404, code="analysis_request_not_found")

        allowed = check_token_permission(
            permissions=token_permissions,
            operation="file_download",
            automation_id=shared_request.automation_id,
        )
        if not allowed:
            raise AppException("Token cannot download this execution file.", status_code=403, code="file_download_permission_denied")

        absolute_path = self._assert_storage_consistency(file_path=execution_file.file_path, expected_size=execution_file.file_size)
        return DownloadableFile(
            absolute_path=absolute_path,
            file_name=execution_file.file_name,
            mime_type=execution_file.mime_type,
            checksum=execution_file.checksum,
        )

    def list_execution_files(self, execution_id: UUID) -> list[DjangoAiExecutionFile]:
        return self.execution_files.list_by_execution_id(execution_id)

    def list_execution_files_for_token(
        self,
        *,
        execution_id: UUID,
        token_permissions: list[DjangoAiApiTokenPermission],
    ) -> list[DjangoAiExecutionFile]:
        shared_execution = self.shared_analysis.get_execution_by_id(execution_id)
        if shared_execution is None:
            raise AppException("Execution not found.", status_code=404, code="execution_not_found")

        shared_request = self.shared_analysis.get_request_by_id(shared_execution.analysis_request_id)
        if shared_request is None:
            raise AppException("Related analysis request not found.", status_code=404, code="analysis_request_not_found")

        allowed = check_token_permission(
            permissions=token_permissions,
            operation="file_download",
            automation_id=shared_request.automation_id,
        )
        if not allowed:
            raise AppException(
                "Token cannot list execution files for this execution.",
                status_code=403,
                code="file_download_permission_denied",
            )

        return self.execution_files.list_by_execution_id(execution_id)
