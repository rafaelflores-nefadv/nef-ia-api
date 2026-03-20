from uuid import uuid4

from app.core.exceptions import AppException
from app.services.execution_engine import (
    EngineExecutionInput,
    ExecutionFileKind,
    ExecutionInputType,
    ExecutionOutputType,
    ExecutionParserStrategy,
    ExecutionProcessingMode,
)
from app.services.execution_observability import (
    classify_execution_error,
    summarize_processing_inputs,
    summarize_processing_plan,
)


def test_summarize_processing_inputs_is_safe_and_structured() -> None:
    inputs = [
        EngineExecutionInput(
            request_file_id=uuid4(),
            role="primary",
            order_index=0,
            file_name="principal.xlsx",
            file_path="requests/x/principal.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_kind=ExecutionFileKind.TABULAR,
            source="linked",
        ),
        EngineExecutionInput(
            request_file_id=uuid4(),
            role="context",
            order_index=1,
            file_name="contexto.pdf",
            file_path="requests/x/contexto.pdf",
            mime_type="application/pdf",
            file_kind=ExecutionFileKind.TEXTUAL,
            source="linked",
        ),
    ]

    summary = summarize_processing_inputs(inputs)

    assert summary["input_file_count"] == 2
    assert summary["roles"]["primary"] == 1
    assert summary["roles"]["context"] == 1
    assert summary["kinds"]["tabular"] == 1
    assert summary["kinds"]["textual"] == 1
    assert len(summary["inputs"]) == 2
    assert "file_path" not in summary["inputs"][0]
    assert "file_name" not in summary["inputs"][0]


def test_summarize_processing_plan_exposes_engine_dimensions() -> None:
    primary = EngineExecutionInput(
        request_file_id=uuid4(),
        role="primary",
        order_index=0,
        file_name="a.csv",
        file_path="requests/x/a.csv",
        mime_type="text/csv",
        file_kind=ExecutionFileKind.TABULAR,
        source="linked",
    )
    context = EngineExecutionInput(
        request_file_id=uuid4(),
        role="context",
        order_index=1,
        file_name="b.pdf",
        file_path="requests/x/b.pdf",
        mime_type="application/pdf",
        file_kind=ExecutionFileKind.TEXTUAL,
        source="linked",
    )
    from app.services.execution_engine import EngineExecutionPlan

    plan = EngineExecutionPlan(
        input_type=ExecutionInputType.TABULAR_WITH_CONTEXT,
        processing_mode=ExecutionProcessingMode.ROW_BY_ROW_WITH_CONTEXT,
        output_type=ExecutionOutputType.SPREADSHEET_OUTPUT,
        parser_strategy=ExecutionParserStrategy.TABULAR_STRUCTURED,
        primary_input=primary,
        context_inputs=[context],
        ordered_inputs=[primary, context],
    )

    summary = summarize_processing_plan(plan)
    assert summary["input_type"] == "tabular_with_context"
    assert summary["processing_mode"] == "row_by_row_with_context"
    assert summary["output_type"] == "spreadsheet_output"
    assert summary["parser_strategy"] == "tabular_structured"
    assert summary["context_file_count"] == 1


def test_classify_execution_error_assigns_category_and_phase() -> None:
    exc = AppException(
        "Failed to parse spreadsheet.",
        status_code=422,
        code="tabular_file_parse_error",
    )
    diagnostic = classify_execution_error(exc, failure_phase="execution.pipeline.file_parse")
    assert diagnostic.error_code == "tabular_file_parse_error"
    assert diagnostic.error_category == "input_read_parse"
    assert diagnostic.failure_phase == "execution.pipeline.file_parse"


def test_classify_execution_error_maps_hard_limits_to_system_limit() -> None:
    exc = AppException(
        "Execution exceeded hard limit of provider calls.",
        status_code=422,
        code="provider_calls_hard_limit_exceeded",
    )
    diagnostic = classify_execution_error(exc, failure_phase="execution.pipeline.provider_call")
    assert diagnostic.error_code == "provider_calls_hard_limit_exceeded"
    assert diagnostic.error_category == "system_limit"
    assert diagnostic.failure_phase == "execution.pipeline.provider_call"


def test_classify_execution_error_maps_profile_limits_to_system_limit() -> None:
    exc = AppException(
        "Execution exceeded profile limit of provider calls.",
        status_code=422,
        code="provider_calls_profile_limit_exceeded",
    )
    diagnostic = classify_execution_error(exc, failure_phase="execution.pipeline.provider_call")
    assert diagnostic.error_code == "provider_calls_profile_limit_exceeded"
    assert diagnostic.error_category == "system_limit"
    assert diagnostic.failure_phase == "execution.pipeline.provider_call"
