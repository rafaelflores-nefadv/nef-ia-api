from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from fastapi import UploadFile
from pypdf import PdfReader

from app.core.exceptions import AppException


class FileTextExtractorService:
    allowed_extensions = {".pdf", ".docx"}

    def extract_from_upload(self, upload_file: UploadFile) -> str:
        filename = str(upload_file.filename or "").strip()
        if not filename:
            raise AppException(
                "File is required.",
                status_code=400,
                code="missing_file",
            )

        extension = Path(filename).suffix.lower()
        if extension not in self.allowed_extensions:
            raise AppException(
                "Unsupported resume file extension.",
                status_code=400,
                code="invalid_resume_file_extension",
                details={"allowed_extensions": sorted(self.allowed_extensions)},
            )

        try:
            content = upload_file.file.read()
        except Exception as exc:
            raise AppException(
                "Failed to read uploaded file.",
                status_code=500,
                code="resume_file_read_failed",
            ) from exc

        if not content or not content.strip():
            raise AppException(
                "Uploaded file is empty.",
                status_code=400,
                code="empty_resume_file",
            )

        return self.extract_from_bytes(content=content, extension=extension)

    def extract_from_bytes(self, *, content: bytes, extension: str) -> str:
        normalized_extension = str(extension or "").strip().lower()
        if normalized_extension == ".pdf":
            text = self._extract_pdf_text(content)
        elif normalized_extension == ".docx":
            text = self._extract_docx_text(content)
        else:
            raise AppException(
                "Unsupported resume file extension.",
                status_code=400,
                code="invalid_resume_file_extension",
                details={"allowed_extensions": sorted(self.allowed_extensions)},
            )

        cleaned = text.strip()
        if not cleaned:
            raise AppException(
                "Text could not be extracted from the file.",
                status_code=422,
                code="resume_text_not_extractable",
            )
        return cleaned

    def _extract_pdf_text(self, content: bytes) -> str:
        try:
            reader = PdfReader(BytesIO(content))
            parts = [(page.extract_text() or "").strip() for page in reader.pages]
        except AppException:
            raise
        except Exception as exc:
            raise AppException(
                "Failed to extract text from PDF file.",
                status_code=500,
                code="resume_pdf_extraction_failed",
            ) from exc
        return "\n".join(part for part in parts if part)

    def _extract_docx_text(self, content: bytes) -> str:
        try:
            document = Document(BytesIO(content))
            paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs]
        except AppException:
            raise
        except Exception as exc:
            raise AppException(
                "Failed to extract text from DOCX file.",
                status_code=500,
                code="resume_docx_extraction_failed",
            ) from exc
        return "\n".join(paragraph for paragraph in paragraphs if paragraph)
