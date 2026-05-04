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

    try:
        service._resolve_execution_output_contract(
            automation_id=uuid4(),
            automation_slug="automacao-sem-contrato",
            processing_plan=processing_plan,
            prompt_template=None,
            runtime_output_type=None,
            runtime_result_parser=None,
            runtime_result_formatter=None,
            runtime_output_schema=None,
        )
    except AppException as exc:
        assert exc.payload.code == "execution_output_contract_required"
        return

    raise AssertionError("Expected execution_output_contract_required for tabular execution without explicit contract.")
