import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from uuid import UUID

from app.core.exceptions import AppException

INPUT_ROLE_PRIMARY = "primary"
INPUT_ROLE_CONTEXT = "context"
ALLOWED_INPUT_ROLES = {INPUT_ROLE_PRIMARY, INPUT_ROLE_CONTEXT}


class ExecutionFileKind(str, Enum):
    TABULAR = "tabular"
    TEXTUAL = "textual"
    UNSUPPORTED = "unsupported"


class ExecutionInputType(str, Enum):
    TEXT = "text"
    TABULAR = "tabular"
    MULTI_TEXT = "multi_text"
    TABULAR_WITH_CONTEXT = "tabular_with_context"


class ExecutionProcessingMode(str, Enum):
    SINGLE_PASS = "single_pass"
    ROW_BY_ROW = "row_by_row"
    ROW_BY_ROW_WITH_CONTEXT = "row_by_row_with_context"


class ExecutionOutputType(str, Enum):
    TEXT_OUTPUT = "text_output"
    SPREADSHEET_OUTPUT = "spreadsheet_output"


class ExecutionParserStrategy(str, Enum):
    TEXT_RAW = "text_raw"
    TABULAR_STRUCTURED = "tabular_structured"


@dataclass(slots=True)
class EngineExecutionInput:
    request_file_id: UUID
    role: str
    order_index: int
    file_name: str
    file_path: str
    mime_type: str | None
    file_kind: ExecutionFileKind
    source: str


@dataclass(slots=True)
class EngineExecutionPlan:
    input_type: ExecutionInputType
    processing_mode: ExecutionProcessingMode
    output_type: ExecutionOutputType
    parser_strategy: ExecutionParserStrategy
    primary_input: EngineExecutionInput
    context_inputs: list[EngineExecutionInput]
    ordered_inputs: list[EngineExecutionInput]


@dataclass(slots=True)
class OutputFileDescriptor:
    output_type: ExecutionOutputType
    file_name: str
    mime_type: str


class ExecutionOutputPolicy:
    def build_output_file(self, *, execution_id: UUID, output_type: ExecutionOutputType) -> OutputFileDescriptor:
        if output_type == ExecutionOutputType.TEXT_OUTPUT:
            return OutputFileDescriptor(
                output_type=output_type,
                file_name=f"execution_{execution_id}.txt",
                mime_type="text/plain",
            )
        if output_type == ExecutionOutputType.SPREADSHEET_OUTPUT:
            return OutputFileDescriptor(
                output_type=output_type,
                file_name=f"execution_{execution_id}_resultado.xlsx",
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        raise AppException(
            "Output type is not supported by execution output policy.",
            status_code=422,
            code="execution_output_type_invalid",
            details={"output_type": str(output_type)},
        )


class ExecutionStrategyEngine:
    def __init__(
        self,
        *,
        tabular_extensions: set[str],
        textual_extensions: set[str],
        tabular_mime_hints: set[str],
        textual_mime_hints: set[str],
    ) -> None:
        self.tabular_extensions = {item.lower() for item in tabular_extensions}
        self.textual_extensions = {item.lower() for item in textual_extensions}
        self.tabular_mime_hints = {item.lower() for item in tabular_mime_hints}
        self.textual_mime_hints = {item.lower() for item in textual_mime_hints}

    def detect_file_kind(
        self,
        *,
        file_name: str,
        mime_type: str | None,
    ) -> ExecutionFileKind:
        extension = Path(str(file_name or "")).suffix.lower()
        normalized_mime = str(mime_type or "").strip().lower()

        if extension in self.tabular_extensions:
            return ExecutionFileKind.TABULAR
        if extension in self.textual_extensions:
            return ExecutionFileKind.TEXTUAL
        if normalized_mime in self.tabular_mime_hints:
            return ExecutionFileKind.TABULAR
        if normalized_mime.startswith("text/"):
            return ExecutionFileKind.TEXTUAL
        if normalized_mime in self.textual_mime_hints:
            return ExecutionFileKind.TEXTUAL
        return ExecutionFileKind.UNSUPPORTED

    def resolve_plan(self, *, processing_inputs: list[EngineExecutionInput]) -> EngineExecutionPlan:
        ordered_inputs = sorted(processing_inputs, key=lambda item: item.order_index)
        if not ordered_inputs:
            raise AppException(
                "Execution does not have input files configured.",
                status_code=409,
                code="execution_inputs_missing",
            )

        invalid_roles = sorted({item.role for item in ordered_inputs if item.role not in ALLOWED_INPUT_ROLES})
        if invalid_roles:
            raise AppException(
                "Execution input contains invalid roles.",
                status_code=422,
                code="execution_input_role_invalid",
                details={"invalid_roles": invalid_roles, "allowed_roles": sorted(ALLOWED_INPUT_ROLES)},
            )

        primary_inputs = [item for item in ordered_inputs if item.role == INPUT_ROLE_PRIMARY]
        if len(primary_inputs) != 1:
            raise AppException(
                "Execution input roles are inconsistent: exactly one primary file is required.",
                status_code=422,
                code="execution_primary_input_invalid",
                details={"primary_count": len(primary_inputs)},
            )
        primary_input = primary_inputs[0]
        context_inputs = [item for item in ordered_inputs if item.role == INPUT_ROLE_CONTEXT]

        unsupported_inputs = [item for item in ordered_inputs if item.file_kind == ExecutionFileKind.UNSUPPORTED]
        if unsupported_inputs:
            raise AppException(
                "Execution contains unsupported file types for processing.",
                status_code=422,
                code="execution_input_type_unsupported",
                details={
                    "unsupported_files": [
                        {
                            "request_file_id": str(item.request_file_id),
                            "file_name": item.file_name,
                            "mime_type": item.mime_type,
                        }
                        for item in unsupported_inputs
                    ]
                },
            )

        tabular_inputs = [item for item in ordered_inputs if item.file_kind == ExecutionFileKind.TABULAR]
        if len(tabular_inputs) > 1:
            raise AppException(
                "Multiple tabular files in the same execution are not supported yet.",
                status_code=422,
                code="multiple_tabular_inputs_not_supported",
                details={"request_file_ids": [str(item.request_file_id) for item in tabular_inputs]},
            )

        if tabular_inputs:
            tabular_input = tabular_inputs[0]
            if primary_input.request_file_id != tabular_input.request_file_id:
                raise AppException(
                    "When a tabular file is present, it must be marked as primary.",
                    status_code=422,
                    code="tabular_primary_required",
                    details={"primary_request_file_id": str(primary_input.request_file_id)},
                )
            non_text_contexts = [item for item in context_inputs if item.file_kind != ExecutionFileKind.TEXTUAL]
            if non_text_contexts:
                raise AppException(
                    "Tabular execution accepts only textual context files.",
                    status_code=422,
                    code="tabular_context_type_invalid",
                    details={"request_file_ids": [str(item.request_file_id) for item in non_text_contexts]},
                )
            input_type = (
                ExecutionInputType.TABULAR_WITH_CONTEXT
                if context_inputs
                else ExecutionInputType.TABULAR
            )
            processing_mode = (
                ExecutionProcessingMode.ROW_BY_ROW_WITH_CONTEXT
                if context_inputs
                else ExecutionProcessingMode.ROW_BY_ROW
            )
            return EngineExecutionPlan(
                input_type=input_type,
                processing_mode=processing_mode,
                output_type=ExecutionOutputType.SPREADSHEET_OUTPUT,
                parser_strategy=ExecutionParserStrategy.TABULAR_STRUCTURED,
                primary_input=primary_input,
                context_inputs=context_inputs,
                ordered_inputs=ordered_inputs,
            )

        if primary_input.file_kind != ExecutionFileKind.TEXTUAL:
            raise AppException(
                "Unsupported execution input combination.",
                status_code=422,
                code="invalid_execution_input_combination",
            )

        input_type = ExecutionInputType.MULTI_TEXT if len(ordered_inputs) > 1 else ExecutionInputType.TEXT
        return EngineExecutionPlan(
            input_type=input_type,
            processing_mode=ExecutionProcessingMode.SINGLE_PASS,
            output_type=ExecutionOutputType.TEXT_OUTPUT,
            parser_strategy=ExecutionParserStrategy.TEXT_RAW,
            primary_input=primary_input,
            context_inputs=context_inputs,
            ordered_inputs=ordered_inputs,
        )


class ExecutionResponseParser:
    def __init__(self, *, structured_output_aliases: dict[str, set[str]]) -> None:
        self.structured_output_aliases = structured_output_aliases

    def parse(self, *, parser_strategy: ExecutionParserStrategy, output_text: str) -> str | dict[str, str]:
        if parser_strategy == ExecutionParserStrategy.TEXT_RAW:
            return str(output_text or "").strip()
        if parser_strategy == ExecutionParserStrategy.TABULAR_STRUCTURED:
            return self._parse_structured_tabular_output(output_text=output_text)
        raise AppException(
            "Parser strategy is not supported.",
            status_code=422,
            code="execution_parser_strategy_invalid",
            details={"parser_strategy": str(parser_strategy)},
        )

    def _parse_structured_tabular_output(self, *, output_text: str) -> dict[str, str]:
        parsed = {key: "" for key in self.structured_output_aliases}
        parsed.update(self._parse_structured_output_json(output_text=output_text))
        current_field: str | None = None
        for raw_line in str(output_text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue

            normalized_line = self._strip_list_prefix(line)
            label_and_value = self._split_label_and_value(normalized_line)
            if label_and_value is not None:
                label_raw, value_raw = label_and_value
                matched_field = self._resolve_structured_output_field(label_raw)
                if matched_field is not None:
                    parsed[matched_field] = value_raw.strip()
                    current_field = matched_field
                    continue

            if current_field is not None:
                parsed[current_field] = (
                    f"{parsed[current_field]}\n{line}".strip()
                    if parsed[current_field]
                    else line
                )
        return parsed

    def _parse_structured_output_json(self, *, output_text: str) -> dict[str, str]:
        raw = str(output_text or "").strip()
        if not raw or not raw.startswith(("{", "[")):
            return {}
        try:
            loaded = json.loads(raw)
        except Exception:
            return {}

        data: dict[str, object] = {}
        if isinstance(loaded, dict):
            data = loaded
        elif isinstance(loaded, list) and loaded and isinstance(loaded[0], dict):
            data = loaded[0]
        else:
            return {}

        parsed: dict[str, str] = {}
        for raw_key, raw_value in data.items():
            field = self._resolve_structured_output_field(str(raw_key))
            if field is None:
                continue
            parsed[field] = str(raw_value or "").strip()
        return parsed

    @staticmethod
    def _strip_list_prefix(line: str) -> str:
        stripped = re.sub(r"^\s*[-*]\s*", "", line)
        stripped = re.sub(r"^\s*\d+[.)]\s*", "", stripped)
        return stripped.strip()

    @staticmethod
    def _split_label_and_value(line: str) -> tuple[str, str] | None:
        for separator in (":", "="):
            if separator in line:
                label, value = line.split(separator, 1)
                normalized_label = label.strip().strip("*").strip("_").strip()
                if normalized_label:
                    return normalized_label, value
        return None

    def _resolve_structured_output_field(self, label_raw: str) -> str | None:
        label_key = self._normalize_key(label_raw).replace("_", " ")
        if not label_key:
            return None
        for field_name, aliases in self.structured_output_aliases.items():
            for alias in aliases:
                if label_key == self._normalize_key(alias).replace("_", " "):
                    return field_name
        return None

    @staticmethod
    def _normalize_key(value: str) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        normalized = unicodedata.normalize("NFKD", raw)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
        return normalized
