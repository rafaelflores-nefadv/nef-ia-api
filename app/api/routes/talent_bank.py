from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.dependencies.security import get_current_token
from app.core.exceptions import AppException
from app.models.operational import DjangoAiApiToken
from app.schemas.resume import ResumeParseRequest, ResumeParseResponse
from app.services.file_text_extractor import FileTextExtractorService
from app.services.resume_parser_service import ResumeParserService

router = APIRouter(prefix="/api/v1/talentos", tags=["talent-bank"])


@router.post("/curriculos/parse", response_model=ResumeParseResponse, status_code=status.HTTP_200_OK)
def parse_resume_file(
    file: UploadFile | None = File(default=None),
    _: DjangoAiApiToken = Depends(get_current_token),
) -> ResumeParseResponse:
    if file is None:
        raise AppException(
            "File is required.",
            status_code=400,
            code="missing_file",
        )

    extracted_text = FileTextExtractorService().extract_from_upload(file)
    return ResumeParserService().parse(extracted_text)


@router.post("/curriculos/parse-text", response_model=ResumeParseResponse, status_code=status.HTTP_200_OK)
def parse_resume_text(
    payload: ResumeParseRequest,
    _: DjangoAiApiToken = Depends(get_current_token),
) -> ResumeParseResponse:
    text = str(payload.texto or "").strip()
    if not text:
        raise AppException(
            "Resume text is required.",
            status_code=422,
            code="empty_resume_text",
        )
    return ResumeParserService().parse(text)
