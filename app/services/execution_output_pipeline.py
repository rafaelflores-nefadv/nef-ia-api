from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.core.exceptions import AppException
from app.services.execution_engine import (
    ExecutionFormatterStrategy,
    ExecutionOutputContract,
    ExecutionOutputPolicy,
    ExecutionOutputSchema,
)


@dataclass(slots=True)
class TabularNormalizationContext:
    original_header_map: dict[str, str]


@dataclass(slots=True)
class FormattedExecutionOutput:
    content: bytes
    file_name: str
    mime_type: str


class TextExecutionFormatter(Protocol):
    def format_text(
        self,
        *,
        execution_id: UUID,
        output_text: str,
        output_contract: ExecutionOutputContract,
        output_policy: ExecutionOutputPolicy,
    ) -> FormattedExecutionOutput:
        ...


class TabularExecutionFormatter(Protocol):
    def format_tabular(
        self,
        *,
        execution_id: UUID,
        rows: list[dict[str, Any]],
        columns: list[str],
        output_contract: ExecutionOutputContract,
        output_policy: ExecutionOutputPolicy,
        workbook_builder,
    ) -> FormattedExecutionOutput:  # type: ignore[no-untyped-def]
        ...


class ExecutionResultNormalizer:
    def normalize_text_chunk(self, *, parsed_chunk: str | dict[str, str]) -> str:
        if isinstance(parsed_chunk, dict):
            serialized = json.dumps(parsed_chunk, ensure_ascii=False)
            return serialized.strip()
        return str(parsed_chunk or "").strip()

    @staticmethod
    def merge_text_chunks(*, chunks: list[str]) -> str:
        return "\n\n".join(chunk for chunk in chunks if chunk).strip()

    @staticmethod
    def build_tabular_context(
        *,
        input_headers: list[str],
        output_schema: ExecutionOutputSchema,
    ) -> TabularNormalizationContext:
        if not output_schema.include_input_columns:
            return TabularNormalizationContext(original_header_map={})
        original_header_map: dict[str, str] = {}
        reserved_columns = set(output_schema.columns)
        if output_schema.row_origin_column:
            reserved_columns.add(output_schema.row_origin_column)
        if output_schema.status_column:
            reserved_columns.add(output_schema.status_column)
        if output_schema.error_column:
            reserved_columns.add(output_schema.error_column)
        for header in input_headers:
            mapped_header = header
            if mapped_header in reserved_columns:
                mapped_header = f"{output_schema.input_collision_prefix}{header}"
            original_header_map[header] = mapped_header
        return TabularNormalizationContext(original_header_map=original_header_map)

    @staticmethod
    def build_tabular_output_row(
        *,
        row_index: int,
        row_values: dict[str, Any],
        prompt_fields: dict[str, str],
        output_schema: ExecutionOutputSchema,
        context: TabularNormalizationContext,
    ) -> dict[str, Any]:
        output_row = {column: "" for column in output_schema.columns}
        if output_schema.include_input_columns and output_schema.row_origin_column:
            output_row[output_schema.row_origin_column] = row_index
        for field_name, column_name in output_schema.prompt_field_columns.items():
            output_row[column_name] = str(prompt_fields.get(field_name) or "").strip()
        if output_schema.status_column:
            output_row[output_schema.status_column] = "erro"
        if output_schema.error_column:
            output_row[output_schema.error_column] = ""
        if output_schema.include_input_columns:
            for original_header, mapped_header in context.original_header_map.items():
                output_row[mapped_header] = row_values.get(original_header, "")
        return output_row

    @staticmethod
    def normalize_tabular_row_result(
        *,
        parsed_output: str | dict[str, Any],
        output_schema: ExecutionOutputSchema,
    ) -> dict[str, str]:
        if not isinstance(parsed_output, dict):
            raise AppException(
                "Tabular parser returned invalid output.",
                status_code=422,
                code="tabular_parser_invalid_output",
            )

        normalized: dict[str, str] = {}
        ai_columns = set(output_schema.ai_output_columns)
        alias_fields = (
            output_schema.structured_output_aliases
            if not ai_columns
            else {field_name: aliases for field_name, aliases in output_schema.structured_output_aliases.items() if field_name in ai_columns}
        )

        for field_name in alias_fields:
            normalized[field_name] = ExecutionResultNormalizer._normalize_tabular_cell_value(parsed_output.get(field_name))

        if ai_columns:
            for field_name in ai_columns:
                if field_name not in normalized:
                    normalized[field_name] = ExecutionResultNormalizer._normalize_tabular_cell_value(parsed_output.get(field_name))

        for key, value in parsed_output.items():
            normalized_key = str(key or "").strip()
            if not normalized_key:
                continue
            if ai_columns and normalized_key not in ai_columns:
                continue
            if normalized_key not in normalized:
                normalized[normalized_key] = ExecutionResultNormalizer._normalize_tabular_cell_value(value)
        return normalized

    @staticmethod
    def _normalize_tabular_cell_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"

        normalized = str(value or "").strip()
        if not normalized:
            return ""

        normalized = re.sub(r"\r\n?", "\n", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        normalized = ExecutionResultNormalizer._strip_residual_json_wrappers(normalized)
        boolean_candidate = ExecutionResultNormalizer._normalize_boolean_token(normalized)
        if boolean_candidate is not None:
            return boolean_candidate
        return normalized

    @staticmethod
    def _strip_residual_json_wrappers(value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return ""
        normalized = normalized.replace('\\"', '"').replace("\\'", "'")

        # Trim serialization leftovers from partial JSON projections.
        while normalized.endswith(","):
            normalized = normalized[:-1].rstrip()
        while normalized.endswith("}") and "{" not in normalized:
            normalized = normalized[:-1].rstrip()

        for _ in range(2):
            if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
                normalized = normalized[1:-1].strip()
            while normalized.endswith(","):
                normalized = normalized[:-1].rstrip()
            while normalized.endswith("}") and "{" not in normalized:
                normalized = normalized[:-1].rstrip()
        return normalized.strip()

    @staticmethod
    def _normalize_boolean_token(value: str) -> str | None:
        normalized = str(value or "").strip().lower()
        if normalized in {"true", "false"}:
            return normalized
        return None

    @staticmethod
    def build_tabular_output_columns(
        *,
        output_schema: ExecutionOutputSchema,
        context: TabularNormalizationContext,
    ) -> list[str]:
        output_columns: list[str] = []
        if output_schema.include_input_columns:
            if output_schema.row_origin_column:
                output_columns.append(output_schema.row_origin_column)
            output_columns.extend(context.original_header_map.values())
        for column in output_schema.columns:
            if column not in output_columns:
                output_columns.append(column)
        if output_schema.status_column and output_schema.status_column not in output_columns:
            output_columns.append(output_schema.status_column)
        if output_schema.error_column and output_schema.error_column not in output_columns:
            output_columns.append(output_schema.error_column)
        return output_columns


class TextPlainExecutionFormatter:
    def format_text(
        self,
        *,
        execution_id: UUID,
        output_text: str,
        output_contract: ExecutionOutputContract,
        output_policy: ExecutionOutputPolicy,
    ) -> FormattedExecutionOutput:
        descriptor = output_policy.build_output_file(
            execution_id=execution_id,
            output_contract=output_contract,
        )
        return FormattedExecutionOutput(
            content=(output_text or "(sem retorno textual do modelo)").encode("utf-8"),
            file_name=descriptor.file_name,
            mime_type=descriptor.mime_type,
        )


class SpreadsheetTabularExecutionFormatter:
    def format_tabular(
        self,
        *,
        execution_id: UUID,
        rows: list[dict[str, Any]],
        columns: list[str],
        output_contract: ExecutionOutputContract,
        output_policy: ExecutionOutputPolicy,
        workbook_builder,
    ) -> FormattedExecutionOutput:  # type: ignore[no-untyped-def]
        output_bytes = workbook_builder(
            rows=rows,
            columns=columns,
            worksheet_name=output_contract.output_schema.worksheet_name,
        )
        descriptor = output_policy.build_output_file(
            execution_id=execution_id,
            output_contract=output_contract,
        )
        return FormattedExecutionOutput(
            content=output_bytes,
            file_name=descriptor.file_name,
            mime_type=descriptor.mime_type,
        )


class ExecutionFormatterRegistry:
    def __init__(self) -> None:
        self._text_formatters: dict[ExecutionFormatterStrategy, TextExecutionFormatter] = {}
        self._tabular_formatters: dict[ExecutionFormatterStrategy, TabularExecutionFormatter] = {}

    def register_text(
        self,
        *,
        strategy: ExecutionFormatterStrategy,
        formatter: TextExecutionFormatter,
    ) -> None:
        self._text_formatters[strategy] = formatter

    def register_tabular(
        self,
        *,
        strategy: ExecutionFormatterStrategy,
        formatter: TabularExecutionFormatter,
    ) -> None:
        self._tabular_formatters[strategy] = formatter

    def resolve_text(self, *, strategy: ExecutionFormatterStrategy) -> TextExecutionFormatter:
        formatter = self._text_formatters.get(strategy)
        if formatter is None:
            raise AppException(
                "Formatter strategy is not registered for textual output.",
                status_code=422,
                code="execution_formatter_strategy_invalid",
                details={"formatter_strategy": strategy.value, "channel": "text"},
            )
        return formatter

    def resolve_tabular(self, *, strategy: ExecutionFormatterStrategy) -> TabularExecutionFormatter:
        formatter = self._tabular_formatters.get(strategy)
        if formatter is None:
            raise AppException(
                "Formatter strategy is not registered for tabular output.",
                status_code=422,
                code="execution_formatter_strategy_invalid",
                details={"formatter_strategy": strategy.value, "channel": "tabular"},
            )
        return formatter


class ExecutionResultFormatter:
    def __init__(self, *, registry: ExecutionFormatterRegistry | None = None) -> None:
        if registry is None:
            registry = ExecutionFormatterRegistry()
            registry.register_text(
                strategy=ExecutionFormatterStrategy.TEXT_PLAIN,
                formatter=TextPlainExecutionFormatter(),
            )
            registry.register_tabular(
                strategy=ExecutionFormatterStrategy.SPREADSHEET_TABULAR,
                formatter=SpreadsheetTabularExecutionFormatter(),
            )
        self.registry = registry

    def format_text_output(
        self,
        *,
        execution_id: UUID,
        output_text: str,
        output_contract: ExecutionOutputContract,
        output_policy: ExecutionOutputPolicy,
    ) -> FormattedExecutionOutput:
        formatter = self.registry.resolve_text(strategy=output_contract.formatter_strategy)
        return formatter.format_text(
            execution_id=execution_id,
            output_text=output_text,
            output_contract=output_contract,
            output_policy=output_policy,
        )

    def format_tabular_output(
        self,
        *,
        execution_id: UUID,
        rows: list[dict[str, Any]],
        columns: list[str],
        output_contract: ExecutionOutputContract,
        output_policy: ExecutionOutputPolicy,
        workbook_builder,
    ) -> FormattedExecutionOutput:  # type: ignore[no-untyped-def]
        formatter = self.registry.resolve_tabular(strategy=output_contract.formatter_strategy)
        return formatter.format_tabular(
            execution_id=execution_id,
            rows=rows,
            columns=columns,
            output_contract=output_contract,
            output_policy=output_policy,
            workbook_builder=workbook_builder,
        )
