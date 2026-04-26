from __future__ import annotations

import hashlib
import re
from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from fastapi import UploadFile

from app.integrations.storage.base import FileMetadata, StoredFile


class LocalStorageProvider:
    def __init__(self, *, root_path: str | Path, chunk_size_bytes: int = 1024 * 1024) -> None:
        self.root_path = Path(root_path).resolve()
        self.chunk_size_bytes = chunk_size_bytes
        self.root_path.mkdir(parents=True, exist_ok=True)

    def save_uploaded_file(
        self,
        *,
        upload_file: UploadFile,
        category: str,
        entity_id: UUID,
        max_size_bytes: int,
    ) -> StoredFile:
        file_name = self._sanitize_file_name(upload_file.filename or "upload.bin")
        target_path = self._next_available_path(category=category, entity_id=entity_id, subdir="uploads", file_name=file_name)
        checksum = hashlib.sha256()
        total_size = 0

        with target_path.open("wb") as target:
            while True:
                chunk = upload_file.file.read(self.chunk_size_bytes)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > max_size_bytes:
                    target.close()
                    target_path.unlink(missing_ok=True)
                    raise ValueError("File exceeds configured maximum size.")
                checksum.update(chunk)
                target.write(chunk)

        try:
            upload_file.file.seek(0)
        except Exception:
            pass

        return StoredFile(
            relative_path=self._relative_path(target_path),
            absolute_path=target_path,
            file_name=file_name,
            file_size=total_size,
            mime_type=upload_file.content_type,
            checksum=checksum.hexdigest(),
        )

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
        safe_name = self._sanitize_file_name(file_name)
        target_path = self._next_available_path(category=category, entity_id=entity_id, subdir=subdir, file_name=safe_name)
        checksum = hashlib.sha256()
        total_size = 0

        with target_path.open("wb") as target:
            if isinstance(content, bytes):
                checksum.update(content)
                target.write(content)
                total_size = len(content)
            else:
                while True:
                    chunk = content.read(self.chunk_size_bytes)
                    if not chunk:
                        break
                    checksum.update(chunk)
                    target.write(chunk)
                    total_size += len(chunk)

        return StoredFile(
            relative_path=self._relative_path(target_path),
            absolute_path=target_path,
            file_name=safe_name,
            file_size=total_size,
            mime_type=mime_type,
            checksum=checksum.hexdigest(),
        )

    def get_file_metadata(self, relative_path: str) -> FileMetadata:
        absolute_path = self._resolve_relative_path(relative_path)
        if not absolute_path.exists() or not absolute_path.is_file():
            return FileMetadata(exists=False, absolute_path=absolute_path)
        return FileMetadata(exists=True, absolute_path=absolute_path, file_size=absolute_path.stat().st_size)

    def delete_file(self, relative_path: str) -> None:
        absolute_path = self._resolve_relative_path(relative_path)
        if absolute_path.exists() and absolute_path.is_file():
            absolute_path.unlink()

    def open_file(self, relative_path: str) -> AbstractContextManager[BinaryIO]:
        return self._resolve_relative_path(relative_path).open("rb")

    def _next_available_path(self, *, category: str, entity_id: UUID, subdir: str, file_name: str) -> Path:
        directory = self.root_path / self._sanitize_path_part(category) / str(entity_id) / self._sanitize_path_part(subdir)
        directory.mkdir(parents=True, exist_ok=True)

        candidate = directory / file_name
        if not candidate.exists():
            return candidate

        stem = candidate.stem
        suffix = candidate.suffix
        index = 1
        while True:
            candidate = directory / f"{stem}-{index}{suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    def _resolve_relative_path(self, relative_path: str) -> Path:
        absolute_path = (self.root_path / relative_path).resolve()
        if self.root_path not in absolute_path.parents and absolute_path != self.root_path:
            raise ValueError("Path escapes storage root.")
        return absolute_path

    def _relative_path(self, absolute_path: Path) -> str:
        return absolute_path.relative_to(self.root_path).as_posix()

    @staticmethod
    def _sanitize_file_name(file_name: str) -> str:
        name = Path(file_name).name.strip()
        name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
        return name or "file"

    @staticmethod
    def _sanitize_path_part(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
        return cleaned.strip("._-") or "default"
