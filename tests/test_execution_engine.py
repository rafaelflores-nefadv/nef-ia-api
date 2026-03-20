from uuid import uuid4

import pytest

from app.core.exceptions import AppException
from app.services.execution_engine import (
    EngineExecutionInput,
    ExecutionFileKind,
    ExecutionInputType,
    ExecutionOutputPolicy,
    ExecutionOutputType,
    ExecutionParserStrategy,
    ExecutionProcessingMode,
    ExecutionResponseParser,
    ExecutionStrategyEngine,
)


def _build_engine() -> ExecutionStrategyEngine:
    return ExecutionStrategyEngine(
        tabular_extensions={".xlsx", ".xls", ".csv"},
        textual_extensions={".pdf", ".txt"},
        tabular_mime_hints={"text/csv"},
        textual_mime_hints={"application/pdf"},
    )


def _build_input(*, role: str, order_index: int, file_name: str, file_kind: ExecutionFileKind) -> EngineExecutionInput:
    return EngineExecutionInput(
        request_file_id=uuid4(),
        role=role,
        order_index=order_index,
        file_name=file_name,
        file_path=f"requests/{file_name}",
        mime_type=None,
        file_kind=file_kind,
        source="linked",
    )


def test_strategy_engine_resolves_single_text_plan() -> None:
    engine = _build_engine()
    plan = engine.resolve_plan(
        processing_inputs=[
            _build_input(role="primary", order_index=0, file_name="input.pdf", file_kind=ExecutionFileKind.TEXTUAL),
        ]
    )
    assert plan.input_type == ExecutionInputType.TEXT
    assert plan.processing_mode == ExecutionProcessingMode.SINGLE_PASS
    assert plan.output_type == ExecutionOutputType.TEXT_OUTPUT
    assert plan.parser_strategy == ExecutionParserStrategy.TEXT_RAW


def test_strategy_engine_resolves_tabular_with_context_plan() -> None:
    engine = _build_engine()
    plan = engine.resolve_plan(
        processing_inputs=[
            _build_input(role="primary", order_index=0, file_name="input.csv", file_kind=ExecutionFileKind.TABULAR),
            _build_input(role="context", order_index=1, file_name="context.pdf", file_kind=ExecutionFileKind.TEXTUAL),
        ]
    )
    assert plan.input_type == ExecutionInputType.TABULAR_WITH_CONTEXT
    assert plan.processing_mode == ExecutionProcessingMode.ROW_BY_ROW_WITH_CONTEXT
    assert plan.output_type == ExecutionOutputType.SPREADSHEET_OUTPUT
    assert plan.parser_strategy == ExecutionParserStrategy.TABULAR_STRUCTURED


def test_strategy_engine_rejects_multiple_tabular_inputs() -> None:
    engine = _build_engine()
    with pytest.raises(AppException) as exc_info:
        engine.resolve_plan(
            processing_inputs=[
                _build_input(role="primary", order_index=0, file_name="a.csv", file_kind=ExecutionFileKind.TABULAR),
                _build_input(role="context", order_index=1, file_name="b.xlsx", file_kind=ExecutionFileKind.TABULAR),
            ]
        )
    assert exc_info.value.payload.code == "multiple_tabular_inputs_not_supported"


def test_response_parser_structured_tabular_has_fallback() -> None:
    parser = ExecutionResponseParser(
        structured_output_aliases={
            "classificacao_da_planilha": {"classificacao da planilha", "classificacao_planilha"},
            "classificacao_correta": {"classificacao correta", "classificacao_correta"},
            "veredito": {"veredito"},
            "motivo": {"motivo"},
            "trecho_determinante": {"trecho determinante", "trecho_determinante"},
        }
    )
    parsed = parser.parse(
        parser_strategy=ExecutionParserStrategy.TABULAR_STRUCTURED,
        output_text="Veredito: Divergente\nMotivo: Regra aplicada",
    )
    assert isinstance(parsed, dict)
    assert parsed["veredito"] == "Divergente"
    assert parsed["motivo"] == "Regra aplicada"
    assert parsed["classificacao_correta"] == ""


def test_output_policy_explicit_file_types() -> None:
    policy = ExecutionOutputPolicy()
    execution_id = uuid4()
    text_file = policy.build_output_file(execution_id=execution_id, output_type=ExecutionOutputType.TEXT_OUTPUT)
    sheet_file = policy.build_output_file(execution_id=execution_id, output_type=ExecutionOutputType.SPREADSHEET_OUTPUT)

    assert text_file.file_name.endswith(".txt")
    assert text_file.mime_type == "text/plain"
    assert sheet_file.file_name.endswith(".xlsx")
    assert "spreadsheetml.sheet" in sheet_file.mime_type
