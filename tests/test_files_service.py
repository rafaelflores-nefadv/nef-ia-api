import hashlib
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.exceptions import AppException
from app.integrations.storage.local import LocalStorageProvider
from app.models.operational import DjangoAiApiToken, DjangoAiApiTokenPermission, DjangoAiRequestFile
from app.services.file_service import FileService


class FakeSession:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def refresh(self, _: object) -> None:
        return None


class FakeAuditRepository:
    def add(self, audit_log: object) -> object:
        return audit_log


class FakeRequestFileRepository:
    def __init__(self) -> None:
        self.files: dict[UUID, DjangoAiRequestFile] = {}

    def add(self, model: DjangoAiRequestFile) -> DjangoAiRequestFile:
        if model.id is None:
            model.id = uuid4()
        now = datetime.now(timezone.utc)
        if model.created_at is None:
            model.created_at = now
        model.updated_at = now
        self.files[model.id] = model
        return model

    def get_by_id(self, file_id: UUID) -> DjangoAiRequestFile | None:
        return self.files.get(file_id)

    def list_by_request_id(self, analysis_request_id: UUID) -> list[DjangoAiRequestFile]:
        return [item for item in self.files.values() if item.analysis_request_id == analysis_request_id]


class FakeExecutionFileRepository:
    def __init__(self) -> None:
        self.files = {}

    def list_by_execution_id(self, execution_id: UUID) -> list:
        return [item for item in self.files.values() if item.execution_id == execution_id]

    def get_by_id(self, file_id: UUID):  # type: ignore[no-untyped-def]
        return self.files.get(file_id)

    def add(self, model):  # type: ignore[no-untyped-def]
        if model.id is None:
            model.id = uuid4()
        self.files[model.id] = model
        return model


class FakeSharedAnalysisRepository:
    def __init__(self, analysis_request_id: UUID, automation_id: UUID) -> None:
        self.analysis_request_id = analysis_request_id
        self.automation_id = automation_id
        self.executions: dict[UUID, object] = {}

    def get_request_by_id(self, analysis_request_id: UUID):  # type: ignore[no-untyped-def]
        if analysis_request_id != self.analysis_request_id:
            return None
        return SimpleNamespace(id=analysis_request_id, automation_id=self.automation_id)

    def get_execution_by_id(self, execution_id: UUID):  # type: ignore[no-untyped-def]
        return self.executions.get(execution_id)

    def register_execution(self, *, execution_id: UUID, analysis_request_id: UUID | None = None) -> None:
        self.executions[execution_id] = SimpleNamespace(
            id=execution_id,
            analysis_request_id=analysis_request_id or self.analysis_request_id,
        )


def build_upload(filename: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=io.BytesIO(content),
        headers=Headers({"content-type": content_type}),
    )


def build_service(tmp_path, analysis_request_id: UUID, automation_id: UUID) -> FileService:  # type: ignore[no-untyped-def]
    service = FileService(
        operational_session=FakeSession(),  # type: ignore[arg-type]
        shared_session=FakeSession(),  # type: ignore[arg-type]
        storage=LocalStorageProvider(root_path=tmp_path),
    )
    service.request_files = FakeRequestFileRepository()  # type: ignore[assignment]
    service.execution_files = FakeExecutionFileRepository()  # type: ignore[assignment]
    service.shared_analysis = FakeSharedAnalysisRepository(analysis_request_id, automation_id)  # type: ignore[assignment]
    service.audit_logs = FakeAuditRepository()  # type: ignore[assignment]
    return service


def build_token_with_permissions(automation_id: UUID) -> tuple[DjangoAiApiToken, list[DjangoAiApiTokenPermission]]:
    token = DjangoAiApiToken(
        id=uuid4(),
        name="file-token",
        token_hash="hash",
        is_active=True,
        expires_at=None,
        created_by_user_id=uuid4(),
    )
    permission = DjangoAiApiTokenPermission(
        token_id=token.id,
        automation_id=automation_id,
        provider_id=None,
        allow_execution=False,
        allow_file_upload=True,
    )
    return token, [permission]


def test_upload_valid_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    analysis_request_id = uuid4()
    automation_id = uuid4()
    service = build_service(tmp_path, analysis_request_id, automation_id)
    token, permissions = build_token_with_permissions(automation_id)
    upload = build_upload("input.csv", b"col1,col2\n1,2\n", "text/csv")

    saved = service.upload_request_file(
        analysis_request_id=analysis_request_id,
        upload_file=upload,
        api_token=token,
        token_permissions=permissions,
    )

    assert saved.file_size > 0
    assert saved.checksum is not None
    assert len(saved.checksum) == 64
    assert (tmp_path / saved.file_path).exists()


def test_upload_multiple_mixed_files(tmp_path) -> None:  # type: ignore[no-untyped-def]
    analysis_request_id = uuid4()
    automation_id = uuid4()
    service = build_service(tmp_path, analysis_request_id, automation_id)
    token, permissions = build_token_with_permissions(automation_id)
    uploads = [
        build_upload("contrato.pdf", b"%PDF texto", "application/pdf"),
        build_upload("planilha.xlsx", b"xlsx-data", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        build_upload(
            "relatorio.docx",
            b"docx-data",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ]

    saved = service.upload_request_files(
        analysis_request_id=analysis_request_id,
        upload_files=uploads,
        api_token=token,
        token_permissions=permissions,
    )

    assert [item.file_name for item in saved] == ["contrato.pdf", "planilha.xlsx", "relatorio.docx"]
    assert all((tmp_path / item.file_path).exists() for item in saved)


def test_reject_invalid_extension(tmp_path) -> None:  # type: ignore[no-untyped-def]
    analysis_request_id = uuid4()
    automation_id = uuid4()
    service = build_service(tmp_path, analysis_request_id, automation_id)
    token, permissions = build_token_with_permissions(automation_id)
    upload = build_upload("input.exe", b"bad", "application/octet-stream")

    with pytest.raises(AppException) as exc_info:
        service.upload_request_file(
            analysis_request_id=analysis_request_id,
            upload_file=upload,
            api_token=token,
            token_permissions=permissions,
        )
    assert exc_info.value.payload.code == "invalid_file_extension"


def test_reject_legacy_xls_upload(tmp_path) -> None:  # type: ignore[no-untyped-def]
    analysis_request_id = uuid4()
    automation_id = uuid4()
    service = build_service(tmp_path, analysis_request_id, automation_id)
    token, permissions = build_token_with_permissions(automation_id)
    upload = build_upload("legacy.xls", b"legacy", "application/vnd.ms-excel")

    with pytest.raises(AppException) as exc_info:
        service.upload_request_file(
            analysis_request_id=analysis_request_id,
            upload_file=upload,
            api_token=token,
            token_permissions=permissions,
        )
    assert exc_info.value.payload.code == "xls_legacy_not_supported"


def test_reject_empty_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    analysis_request_id = uuid4()
    automation_id = uuid4()
    service = build_service(tmp_path, analysis_request_id, automation_id)
    token, permissions = build_token_with_permissions(automation_id)
    upload = build_upload("input.csv", b"", "text/csv")

    with pytest.raises(AppException) as exc_info:
        service.upload_request_file(
            analysis_request_id=analysis_request_id,
            upload_file=upload,
            api_token=token,
            token_permissions=permissions,
        )
    assert exc_info.value.payload.code == "empty_file"


def test_download_existing_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    analysis_request_id = uuid4()
    automation_id = uuid4()
    payload = b"download,test\n1,2\n"
    service = build_service(tmp_path, analysis_request_id, automation_id)
    token, permissions = build_token_with_permissions(automation_id)
    upload = build_upload("input.csv", payload, "text/csv")

    saved = service.upload_request_file(
        analysis_request_id=analysis_request_id,
        upload_file=upload,
        api_token=token,
        token_permissions=permissions,
    )
    downloadable = service.get_request_file_for_download(file_id=saved.id, token_permissions=permissions)

    with open(downloadable.absolute_path, "rb") as handle:
        assert handle.read() == payload


def test_error_when_file_missing_in_storage(tmp_path) -> None:  # type: ignore[no-untyped-def]
    analysis_request_id = uuid4()
    automation_id = uuid4()
    service = build_service(tmp_path, analysis_request_id, automation_id)
    token, permissions = build_token_with_permissions(automation_id)
    upload = build_upload("input.csv", b"gone\n", "text/csv")

    saved = service.upload_request_file(
        analysis_request_id=analysis_request_id,
        upload_file=upload,
        api_token=token,
        token_permissions=permissions,
    )
    (tmp_path / saved.file_path).unlink()

    with pytest.raises(AppException) as exc_info:
        service.get_request_file_for_download(file_id=saved.id, token_permissions=permissions)
    assert exc_info.value.payload.code == "file_missing_in_storage"


def test_checksum_present_and_correct(tmp_path) -> None:  # type: ignore[no-untyped-def]
    analysis_request_id = uuid4()
    automation_id = uuid4()
    payload = b"checksum,data\n10,20\n"
    expected_checksum = hashlib.sha256(payload).hexdigest()
    service = build_service(tmp_path, analysis_request_id, automation_id)
    token, permissions = build_token_with_permissions(automation_id)
    upload = build_upload("input.csv", payload, "text/csv")

    saved = service.upload_request_file(
        analysis_request_id=analysis_request_id,
        upload_file=upload,
        api_token=token,
        token_permissions=permissions,
    )

    assert saved.checksum == expected_checksum


def test_list_execution_files_for_token(tmp_path) -> None:  # type: ignore[no-untyped-def]
    analysis_request_id = uuid4()
    automation_id = uuid4()
    service = build_service(tmp_path, analysis_request_id, automation_id)
    execution_id = uuid4()
    service.shared_analysis.register_execution(execution_id=execution_id)  # type: ignore[attr-defined]

    file_model = SimpleNamespace(
        id=uuid4(),
        execution_id=execution_id,
        file_type="output",
        file_name="resultado.xlsx",
        file_path="executions/example/output/resultado.xlsx",
        file_size=100,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        checksum="abc",
        created_at=datetime.now(timezone.utc),
    )
    service.execution_files.add(file_model)  # type: ignore[arg-type]

    _, permissions = build_token_with_permissions(automation_id)
    items = service.list_execution_files_for_token(
        execution_id=execution_id,
        token_permissions=permissions,
    )

    assert len(items) == 1
    assert items[0].id == file_model.id
