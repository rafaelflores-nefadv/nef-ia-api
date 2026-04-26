from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from contextlib import AbstractContextManager
from typing import BinaryIO, Protocol
from uuid import UUID

from fastapi import UploadFile


@dataclass(frozen=True, slots=True)
class StoredFile:
    relative_path: str
    absolute_path: Path
    file_name: str
    file_size: int
    mime_type: str | None
    checksum: str


@dataclass(frozen=True, slots=True)
class FileMetadata:
    exists: bool
    absolute_path: Path
    file_size: int | None = None


class StorageProvider(Protocol):
    def save_uploaded_file(
        self,
        *,
        upload_file: UploadFile,
        category: str,
        entity_id: UUID,
        max_size_bytes: int,
    ) -> StoredFile:
        ...

    def save_generated_file(
        self,
        *,
        content: bytes | BinaryIO,
        category: str,
        entity_id: UUID,
        subdir: str,
        file_name: str,
        mime_type: str | None = None,
    ) -> StoredFile:
        ...

    def get_file_metadata(self, relative_path: str) -> FileMetadata:
        ...

    def delete_file(self, relative_path: str) -> None:
        ...

    def open_file(self, relative_path: str) -> AbstractContextManager[BinaryIO]:
        ...
