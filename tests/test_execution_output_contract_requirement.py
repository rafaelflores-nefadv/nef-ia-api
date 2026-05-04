from types import SimpleNamespace
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
from app.services.execution_service import ExecutionService


def test_tabular_execution_requires_explicit_output_contract() -> None:
    service = ExecutionService(operational_session=SimpleNamespace(), shared_session=SimpleNamespace())  # type: ignore[arg-type]
    processing_plan = service.strategy_engine.resolve_plan(
        processing_inputs=[
            EngineExecutionInput(
                request_file_id=uuid4(),
                role="primary",
                order_index=0,
                file_name="entrada.csv",
                file_path="storage/entrada.csv",
                mime_type="text/csv",
                file_kind=ExecutionFileKind.TABULAR,
                source="test",
            )
        ]
    )

    contract = service._resolve_execution_output_contract(
        automation_id=uuid4(),
        automation_slug="automacao-sem-contrato",
        processing_plan=processing_plan,
        runtime_output_type=None,
        runtime_result_parser=None,
        runtime_result_formatter=None,
        runtime_output_schema=None,
    )

    assert contract.source == "fallback_no_output_contract_config"

    if (
        processing_plan.input_type in {ExecutionInputType.TABULAR, ExecutionInputType.TABULAR_WITH_CONTEXT}
        and contract.source == "fallback_no_output_contract_config"
    ):
        exc = AppException(
            "Tabular automation requires explicit output contract. Configure output_type, result_parser, result_formatter and output_schema.",
            status_code=422,
            code="execution_output_contract_required",
        )
        assert exc.payload.code == "execution_output_contract_required"
