import pytest

from app.core.exceptions import AppException
from app.services.execution_engine import ExecutionInputType
from app.services.execution_output_contract import ExecutionOutputContractResolver


def test_output_contract_invalid_output_type_raises() -> None:
    resolver = ExecutionOutputContractResolver()

    with pytest.raises(AppException) as exc_info:
        resolver.resolve(
            input_type=ExecutionInputType.TEXT,
            runtime_output_type="invalid_output_type",
        )

    assert exc_info.value.payload.code == "execution_output_contract_invalid"


def test_output_contract_malformed_schema_raises() -> None:
    resolver = ExecutionOutputContractResolver()

    with pytest.raises(AppException) as exc_info:
        resolver.resolve(
            input_type=ExecutionInputType.TABULAR,
            runtime_output_type="spreadsheet_output",
            runtime_result_parser="tabular_structured",
            runtime_result_formatter="spreadsheet_tabular",
            runtime_output_schema="{malformed-json",
        )

    assert exc_info.value.payload.code == "execution_output_schema_invalid"


def test_output_contract_rejects_operational_column_collision() -> None:
    resolver = ExecutionOutputContractResolver()

    with pytest.raises(AppException) as exc_info:
        resolver.resolve(
            input_type=ExecutionInputType.TABULAR,
            runtime_output_type="spreadsheet_output",
            runtime_result_parser="tabular_structured",
            runtime_result_formatter="spreadsheet_tabular",
            runtime_output_schema={
                "columns": ["linha_origem", "resultado"],
                "status_column": "resultado",
                "error_column": "resultado",
            },
        )

    assert exc_info.value.payload.code == "execution_output_schema_invalid"


def test_output_contract_explicit_schema_can_disable_operational_columns() -> None:
    resolver = ExecutionOutputContractResolver()
    contract = resolver.resolve(
        input_type=ExecutionInputType.TABULAR,
        runtime_output_type="spreadsheet_output",
        runtime_result_parser="tabular_structured",
        runtime_result_formatter="spreadsheet_tabular",
        runtime_output_schema={
            "columns": ["linha_origem", "documento", "classificacao"],
            "structured_output_aliases": {"classificacao": ["classificacao"]},
            "status_column": None,
            "error_column": None,
        },
    )

    assert contract.output_schema.status_column is None
    assert contract.output_schema.error_column is None


def test_output_contract_explicit_columns_default_to_strict_projection() -> None:
    resolver = ExecutionOutputContractResolver()
    contract = resolver.resolve(
        input_type=ExecutionInputType.TABULAR,
        runtime_output_type="spreadsheet_output",
        runtime_result_parser="tabular_structured",
        runtime_result_formatter="spreadsheet_tabular",
        runtime_output_schema={
            "columns": ["coluna_a", "coluna_b"],
            "structured_output_aliases": {"coluna_b": ["coluna_b"]},
        },
    )

    assert contract.output_schema.include_input_columns is False
    assert contract.output_schema.row_origin_column is None
    assert contract.output_schema.columns == ("coluna_a", "coluna_b")


def test_output_contract_rejects_unknown_ai_output_columns() -> None:
    resolver = ExecutionOutputContractResolver()

    with pytest.raises(AppException) as exc_info:
        resolver.resolve(
            input_type=ExecutionInputType.TABULAR,
            runtime_output_type="spreadsheet_output",
            runtime_result_parser="tabular_structured",
            runtime_result_formatter="spreadsheet_tabular",
            runtime_output_schema={
                "columns": ["coluna_a", "coluna_b"],
                "structured_output_aliases": {"coluna_b": ["coluna_b"]},
                "ai_output_columns": ["inexistente"],
            },
        )

    assert exc_info.value.payload.code == "execution_output_schema_invalid"


def test_output_contract_fallback_source_is_explicit_when_automation_has_no_config() -> None:
    resolver = ExecutionOutputContractResolver()
    contract = resolver.resolve(input_type=ExecutionInputType.TEXT)
    assert contract.source == "fallback_no_output_contract_config"


def test_output_contract_rejects_incompatible_text_contract() -> None:
    resolver = ExecutionOutputContractResolver()

    with pytest.raises(AppException) as exc_info:
        resolver.resolve(
            input_type=ExecutionInputType.TEXT,
            runtime_output_type="spreadsheet_output",
            runtime_result_parser="tabular_structured",
            runtime_result_formatter="spreadsheet_tabular",
        )

    assert exc_info.value.payload.code == "execution_output_contract_incompatible"


def test_output_contract_normalizes_legacy_input_column_mappings_source_to_target() -> None:
    resolver = ExecutionOutputContractResolver()
    contract = resolver.resolve(
        input_type=ExecutionInputType.TABULAR,
        runtime_output_type="spreadsheet_output",
        runtime_result_parser="tabular_structured",
        runtime_result_formatter="spreadsheet_tabular",
        runtime_output_schema={
            "columns": ["numero_processo", "descricao", "categoria"],
            "structured_output_aliases": {"categoria": ["categoria"]},
            "ai_output_columns": ["categoria"],
            "input_column_mappings": {
                "Número Processo": "numero_processo",
                "Conteúdo": "descricao",
            },
        },
    )

    assert "Número Processo" not in contract.output_schema.prompt_field_columns
    assert "Conteúdo" not in contract.output_schema.prompt_field_columns
    assert "numero_processo" in contract.output_schema.prompt_field_aliases
    assert "descricao" in contract.output_schema.prompt_field_aliases
    assert "Número Processo" in contract.output_schema.prompt_field_aliases["numero_processo"]
    assert "Conteúdo" in contract.output_schema.prompt_field_aliases["descricao"]


def test_output_contract_rejects_input_column_mapping_with_unresolved_target() -> None:
    resolver = ExecutionOutputContractResolver()

    with pytest.raises(AppException) as exc_info:
        resolver.resolve(
            input_type=ExecutionInputType.TABULAR,
            runtime_output_type="spreadsheet_output",
            runtime_result_parser="tabular_structured",
            runtime_result_formatter="spreadsheet_tabular",
            runtime_output_schema={
                "columns": ["numero_processo", "descricao", "categoria"],
                "structured_output_aliases": {"categoria": ["categoria"]},
                "ai_output_columns": ["categoria"],
                "input_column_mappings": {"Número Processo": "campo_inexistente"},
            },
        )

    assert exc_info.value.payload.code == "execution_output_schema_invalid"
