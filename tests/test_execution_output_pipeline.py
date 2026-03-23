from uuid import uuid4

import pytest

from app.core.exceptions import AppException
from app.services.execution_engine import (
    ExecutionFormatterStrategy,
    ExecutionOutputContract,
    ExecutionOutputPolicy,
    ExecutionOutputSchema,
    ExecutionOutputType,
    ExecutionParserStrategy,
)
from app.services.execution_output_pipeline import (
    ExecutionFormatterRegistry,
    ExecutionResultFormatter,
    ExecutionResultNormalizer,
    FormattedExecutionOutput,
)


class _CustomTabularFormatter:
    def format_tabular(  # type: ignore[no-untyped-def]
        self,
        *,
        execution_id,
        rows,
        columns,
        output_contract,
        output_policy,
        workbook_builder,
    ) -> FormattedExecutionOutput:
        return FormattedExecutionOutput(
            content=b"custom-output",
            file_name="custom-output.bin",
            mime_type="application/octet-stream",
        )


def test_formatter_registry_allows_custom_tabular_formatter_registration() -> None:
    registry = ExecutionFormatterRegistry()
    registry.register_tabular(
        strategy=ExecutionFormatterStrategy.TEXT_PLAIN,
        formatter=_CustomTabularFormatter(),  # type: ignore[arg-type]
    )
    formatter = ExecutionResultFormatter(registry=registry)
    contract = ExecutionOutputContract(
        output_type=ExecutionOutputType.SPREADSHEET_OUTPUT,
        parser_strategy=ExecutionParserStrategy.TABULAR_STRUCTURED,
        formatter_strategy=ExecutionFormatterStrategy.TEXT_PLAIN,
        output_schema=ExecutionOutputSchema(
            columns=("linha_origem",),
        ),
    )

    output = formatter.format_tabular_output(
        execution_id=uuid4(),
        rows=[{"linha_origem": 1}],
        columns=["linha_origem"],
        output_contract=contract,
        output_policy=ExecutionOutputPolicy(),
        workbook_builder=lambda **_: b"unused",
    )

    assert output.content == b"custom-output"
    assert output.file_name == "custom-output.bin"


def test_formatter_registry_rejects_unregistered_strategy() -> None:
    formatter = ExecutionResultFormatter(registry=ExecutionFormatterRegistry())
    contract = ExecutionOutputContract(
        output_type=ExecutionOutputType.SPREADSHEET_OUTPUT,
        parser_strategy=ExecutionParserStrategy.TABULAR_STRUCTURED,
        formatter_strategy=ExecutionFormatterStrategy.SPREADSHEET_TABULAR,
        output_schema=ExecutionOutputSchema(columns=("linha_origem",)),
    )

    with pytest.raises(AppException) as exc_info:
        formatter.format_tabular_output(
            execution_id=uuid4(),
            rows=[{"linha_origem": 1}],
            columns=["linha_origem"],
            output_contract=contract,
            output_policy=ExecutionOutputPolicy(),
            workbook_builder=lambda **_: b"unused",
        )

    assert exc_info.value.payload.code == "execution_formatter_strategy_invalid"


def test_tabular_normalizer_cleans_json_serialization_residues() -> None:
    normalized = ExecutionResultNormalizer.normalize_tabular_row_result(
        parsed_output={
            "categoria": '"ANÁLISE PÓS CITAÇÃO",',
            "prazo": '"Sem prazo",',
            "resumo_do_andamento": '"Resumo final"}',
        },
        output_schema=ExecutionOutputSchema(
            columns=("categoria", "prazo", "resumo_do_andamento"),
            structured_output_aliases={
                "categoria": ("categoria",),
                "prazo": ("prazo",),
                "resumo_do_andamento": ("resumo_do_andamento",),
            },
            ai_output_columns=("categoria", "prazo", "resumo_do_andamento"),
            include_input_columns=False,
        ),
    )

    assert normalized["categoria"] == "ANÁLISE PÓS CITAÇÃO"
    assert normalized["prazo"] == "Sem prazo"
    assert normalized["resumo_do_andamento"] == "Resumo final"


def test_tabular_normalizer_normalizes_boolean_values_consistently() -> None:
    normalized = ExecutionResultNormalizer.normalize_tabular_row_result(
        parsed_output={
            "compromissoAnalista": True,
            "necessitaRevisao": "False",
            "flag_textual_true": " true ",
        },
        output_schema=ExecutionOutputSchema(
            columns=("compromissoAnalista", "necessitaRevisao", "flag_textual_true"),
            structured_output_aliases={
                "compromissoAnalista": ("compromissoAnalista",),
                "necessitaRevisao": ("necessitaRevisao",),
                "flag_textual_true": ("flag_textual_true",),
            },
            ai_output_columns=("compromissoAnalista", "necessitaRevisao", "flag_textual_true"),
            include_input_columns=False,
        ),
    )

    assert normalized["compromissoAnalista"] == "true"
    assert normalized["necessitaRevisao"] == "false"
    assert normalized["flag_textual_true"] == "true"
