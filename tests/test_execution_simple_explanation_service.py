from app.services.execution_simple_explanation_service import (
    CONTROLLED_INVALID_JSON_MESSAGE,
    PENDING_CTR_LABEL,
    ExecutionSimpleExplanationService,
)


def test_generate_simple_debug_explanation_for_pending_result() -> None:
    service = ExecutionSimpleExplanationService()

    payload = service.generate_simple_debug_explanation(
        data_analyzed=[{"descricao": "Texto curto"}],
        prompt_used="Analise a publicacao e classifique o comando processual.",
        final_result=[{"categoria": PENDING_CTR_LABEL}],
        technical_debug=[{"warnings": ["descricao_insuficiente"]}],
        warnings=["descricao_insuficiente"],
        errors=[],
        status="completed",
    )

    assert "automação analisou" in payload["summary"].lower()
    assert "pendente" in payload["reason"].lower()
    assert "insuficiente" in payload["input_issue"].lower()
    assert "envie" in payload["recommendation"].lower()


def test_apply_post_response_validations_handles_empty_description_and_invalid_json() -> None:
    service = ExecutionSimpleExplanationService()

    result = service.apply_post_response_validations(
        row_values={"descricao": ""},
        normalized_output={
            "reclassificacao": "",
            "prazo": "sem prazo",
            "compromissoAnalista": "não identificado",
        },
        json_parse_error="Expecting value",
    )

    assert result.normalized_output["reclassificacao"] == PENDING_CTR_LABEL
    assert result.normalized_output["prazo"] == ""
    assert result.normalized_output["compromissoAnalista"] == ""
    assert CONTROLLED_INVALID_JSON_MESSAGE in result.errors
