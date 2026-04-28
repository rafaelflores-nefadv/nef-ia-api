from __future__ import annotations

from app.core.exceptions import AppException
from app.services.resume_parser_service import ResumeParserService


def test_resume_parser_extracts_email_phone_and_linkedin() -> None:
    service = ResumeParserService()

    result = service.parse(
        "\n".join(
            [
                "Joao Pereira",
                "Sao Paulo / SP",
                "joao.pereira@email.com",
                "+55 (11) 91234-5678",
                "linkedin.com/in/joaopereira",
                "github.com/joaopereira",
            ]
        )
    )

    assert result.dados_pessoais.email == "joao.pereira@email.com"
    assert result.dados_pessoais.telefone == "(11) 91234-5678"
    assert result.dados_pessoais.linkedin == "https://linkedin.com/in/joaopereira"
    assert result.dados_pessoais.github == "https://github.com/joaopereira"
    assert result.dados_pessoais.cidade == "Sao Paulo"
    assert result.dados_pessoais.estado == "SP"


def test_resume_parser_rejects_empty_text() -> None:
    service = ResumeParserService()

    try:
        service.parse("   ")
    except AppException as exc:
        assert exc.payload.code == "empty_resume_text"
    else:
        raise AssertionError("Expected AppException for empty resume text.")
