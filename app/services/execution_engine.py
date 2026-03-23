import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping
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


class ExecutionFormatterStrategy(str, Enum):
    TEXT_PLAIN = "text_plain"
    SPREADSHEET_TABULAR = "spreadsheet_tabular"


LEGACY_STRUCTURED_OUTPUT_ALIASES: dict[str, tuple[str, ...]] = {
    "classificacao_da_planilha": (
        "classificacao da planilha",
        "classificacao_planilha",
    ),
    "classificacao_correta": (
        "classificacao correta",
        "classificacao_correta",
    ),
    "veredito": ("veredito",),
    "motivo": ("motivo",),
    "trecho_determinante": (
        "trecho determinante",
        "trecho_determinante",
    ),
}

LEGACY_TABULAR_OUTPUT_COLUMNS: tuple[str, ...] = (
    "linha_origem",
    "conteudo",
    "prazo_agendado",
    "valor_da_causa",
    "tipo_de_acao",
    "classificacao_da_planilha",
    "classificacao_correta",
    "veredito",
    "motivo",
    "trecho_determinante",
    "status",
    "erro",
)

LEGACY_TABULAR_PROMPT_FIELD_COLUMNS: dict[str, str] = {
    "conteudo": "conteudo",
    "prazo_agendado": "prazo_agendado",
    "valor_da_causa": "valor_da_causa",
    "tipo_de_acao": "tipo_de_acao",
}

LEGACY_TABULAR_PROMPT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "conteudo": (
        "conteudo",
        "conteudo_texto",
        "texto",
        "descricao",
        "descricao_fato",
        "historico",
    ),
    "prazo_agendado": (
        "prazo_agendado",
        "prazo",
        "data_prazo",
        "prazo_previsto",
    ),
    "valor_da_causa": (
        "valor_da_causa",
        "valor_causa",
        "valor",
    ),
    "tipo_de_acao": (
        "tipo_de_acao",
        "tipo_acao",
        "acao",
        "classe_acao",
    ),
}

LEGACY_TABULAR_PROMPT_PLACEHOLDERS: dict[str, str] = {
    "conteudo": "CONTEUDO",
    "prazo_agendado": "PRAZO_AGENDADO",
    "valor_da_causa": "VALOR_DA_CAUSA",
    "tipo_de_acao": "TIPO_DE_ACAO",
}


@dataclass(slots=True, frozen=True)
class ExecutionOutputSchema:
    columns: tuple[str, ...] = ()
    structured_output_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    prompt_field_columns: dict[str, str] = field(default_factory=dict)
    prompt_field_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    prompt_placeholders: dict[str, str] = field(default_factory=dict)
    ai_output_columns: tuple[str, ...] = ()
    row_origin_column: str | None = "linha_origem"
    # Operational fields are optional and explicit. When omitted, no status/error columns are injected.
    status_column: str | None = None
    error_column: str | None = None
    include_input_columns: bool = True
    input_collision_prefix: str = "entrada_"
    worksheet_name: str = "resultado"
    file_name_template: str | None = None
    mime_type: str | None = None


@dataclass(slots=True, frozen=True)
class ExecutionOutputContract:
    output_type: ExecutionOutputType
    parser_strategy: ExecutionParserStrategy
    formatter_strategy: ExecutionFormatterStrategy
    output_schema: ExecutionOutputSchema
    source: str = "fallback"
    source_details: dict[str, Any] = field(default_factory=dict)


def build_default_text_output_contract() -> ExecutionOutputContract:
    return ExecutionOutputContract(
        output_type=ExecutionOutputType.TEXT_OUTPUT,
        parser_strategy=ExecutionParserStrategy.TEXT_RAW,
        formatter_strategy=ExecutionFormatterStrategy.TEXT_PLAIN,
        output_schema=ExecutionOutputSchema(
            file_name_template="execution_{execution_id}.txt",
            mime_type="text/plain",
        ),
        source="fallback_input_type_default",
    )


def build_legacy_tabular_output_contract() -> ExecutionOutputContract:
    return ExecutionOutputContract(
        output_type=ExecutionOutputType.SPREADSHEET_OUTPUT,
        parser_strategy=ExecutionParserStrategy.TABULAR_STRUCTURED,
        formatter_strategy=ExecutionFormatterStrategy.SPREADSHEET_TABULAR,
        output_schema=ExecutionOutputSchema(
            columns=LEGACY_TABULAR_OUTPUT_COLUMNS,
            structured_output_aliases=LEGACY_STRUCTURED_OUTPUT_ALIASES,
            prompt_field_columns=LEGACY_TABULAR_PROMPT_FIELD_COLUMNS,
            prompt_field_aliases=LEGACY_TABULAR_PROMPT_FIELD_ALIASES,
            prompt_placeholders=LEGACY_TABULAR_PROMPT_PLACEHOLDERS,
            row_origin_column="linha_origem",
            status_column="status",
            error_column="erro",
            input_collision_prefix="entrada_",
            worksheet_name="resultado",
            file_name_template="execution_{execution_id}_resultado.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        source="fallback_input_type_default",
    )


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
    primary_input: EngineExecutionInput
    context_inputs: list[EngineExecutionInput]
    ordered_inputs: list[EngineExecutionInput]
    output_type: ExecutionOutputType | None = None
    parser_strategy: ExecutionParserStrategy | None = None
    formatter_strategy: ExecutionFormatterStrategy | None = None
    output_contract: ExecutionOutputContract | None = None

    def __post_init__(self) -> None:
        if self.output_contract is None:
            if self.output_type is None or self.parser_strategy is None:
                raise ValueError("EngineExecutionPlan requires output_contract or output_type/parser_strategy.")
            formatter = self.formatter_strategy
            if formatter is None:
                formatter = (
                    ExecutionFormatterStrategy.TEXT_PLAIN
                    if self.output_type == ExecutionOutputType.TEXT_OUTPUT
                    else ExecutionFormatterStrategy.SPREADSHEET_TABULAR
                )
            default_schema = (
                build_default_text_output_contract().output_schema
                if self.output_type == ExecutionOutputType.TEXT_OUTPUT
                else build_legacy_tabular_output_contract().output_schema
            )
            self.output_contract = ExecutionOutputContract(
                output_type=self.output_type,
                parser_strategy=self.parser_strategy,
                formatter_strategy=formatter,
                output_schema=default_schema,
                source="legacy_plan_fields",
            )

        self.output_type = self.output_contract.output_type
        self.parser_strategy = self.output_contract.parser_strategy
        self.formatter_strategy = self.output_contract.formatter_strategy


@dataclass(slots=True)
class OutputFileDescriptor:
    output_type: ExecutionOutputType
    file_name: str
    mime_type: str


class ExecutionOutputPolicy:
    def build_output_file(
        self,
        *,
        execution_id: UUID,
        output_type: ExecutionOutputType | None = None,
        output_contract: ExecutionOutputContract | None = None,
    ) -> OutputFileDescriptor:
        resolved_contract = output_contract
        if resolved_contract is None:
            if output_type is None:
                raise AppException(
                    "Output type is required when output contract is not provided.",
                    status_code=422,
                    code="execution_output_type_invalid",
                )
            resolved_contract = (
                build_default_text_output_contract()
                if output_type == ExecutionOutputType.TEXT_OUTPUT
                else build_legacy_tabular_output_contract()
            )
        resolved_output_type = resolved_contract.output_type
        resolved_schema = resolved_contract.output_schema

        if resolved_schema.file_name_template and resolved_schema.mime_type:
            try:
                file_name = resolved_schema.file_name_template.format(execution_id=execution_id)
            except Exception:
                file_name = resolved_schema.file_name_template
            return OutputFileDescriptor(
                output_type=resolved_output_type,
                file_name=str(file_name),
                mime_type=str(resolved_schema.mime_type),
            )

        if resolved_output_type == ExecutionOutputType.TEXT_OUTPUT:
            return OutputFileDescriptor(
                output_type=resolved_output_type,
                file_name=f"execution_{execution_id}.txt",
                mime_type="text/plain",
            )
        if resolved_output_type == ExecutionOutputType.SPREADSHEET_OUTPUT:
            return OutputFileDescriptor(
                output_type=resolved_output_type,
                file_name=f"execution_{execution_id}_resultado.xlsx",
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        raise AppException(
            "Output type is not supported by execution output policy.",
            status_code=422,
            code="execution_output_type_invalid",
            details={"output_type": str(resolved_output_type)},
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

    @staticmethod
    def _default_output_contract_for_input_type(input_type: ExecutionInputType) -> ExecutionOutputContract:
        if input_type in {ExecutionInputType.TABULAR, ExecutionInputType.TABULAR_WITH_CONTEXT}:
            return build_legacy_tabular_output_contract()
        return build_default_text_output_contract()

    def resolve_plan(
        self,
        *,
        processing_inputs: list[EngineExecutionInput],
        output_contract: ExecutionOutputContract | None = None,
    ) -> EngineExecutionPlan:
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
            resolved_contract = output_contract or self._default_output_contract_for_input_type(input_type)
            return EngineExecutionPlan(
                input_type=input_type,
                processing_mode=processing_mode,
                output_contract=resolved_contract,
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
        resolved_contract = output_contract or self._default_output_contract_for_input_type(input_type)
        return EngineExecutionPlan(
            input_type=input_type,
            processing_mode=ExecutionProcessingMode.SINGLE_PASS,
            output_contract=resolved_contract,
            primary_input=primary_input,
            context_inputs=context_inputs,
            ordered_inputs=ordered_inputs,
        )

    def with_output_contract(
        self,
        *,
        processing_plan: EngineExecutionPlan,
        output_contract: ExecutionOutputContract,
    ) -> EngineExecutionPlan:
        return EngineExecutionPlan(
            input_type=processing_plan.input_type,
            processing_mode=processing_plan.processing_mode,
            output_contract=output_contract,
            primary_input=processing_plan.primary_input,
            context_inputs=processing_plan.context_inputs,
            ordered_inputs=processing_plan.ordered_inputs,
        )


class ExecutionResponseParser:
    def __init__(self, *, structured_output_aliases: Mapping[str, Iterable[str]] | None = None) -> None:
        self.structured_output_aliases = self._normalize_aliases(structured_output_aliases)

    @staticmethod
    def _normalize_aliases(raw_aliases: Mapping[str, Iterable[str]] | None) -> dict[str, tuple[str, ...]]:
        normalized: dict[str, tuple[str, ...]] = {}
        for field_name, alias_values in (raw_aliases or {}).items():
            aliases = [
                str(alias).strip()
                for alias in alias_values
                if str(alias).strip()
            ]
            if field_name and aliases:
                normalized[str(field_name)] = tuple(dict.fromkeys(aliases))
        return normalized

    def parse(
        self,
        *,
        parser_strategy: ExecutionParserStrategy,
        output_text: str,
        output_schema: ExecutionOutputSchema | None = None,
    ) -> str | dict[str, Any]:
        if parser_strategy == ExecutionParserStrategy.TEXT_RAW:
            return str(output_text or "").strip()
        if parser_strategy == ExecutionParserStrategy.TABULAR_STRUCTURED:
            schema_aliases = output_schema.structured_output_aliases if output_schema is not None else {}
            aliases = self._normalize_aliases(schema_aliases) or self.structured_output_aliases
            return self._parse_structured_tabular_output(output_text=output_text, structured_aliases=aliases)
        raise AppException(
            "Parser strategy is not supported.",
            status_code=422,
            code="execution_parser_strategy_invalid",
            details={"parser_strategy": str(parser_strategy)},
        )

    def _parse_structured_tabular_output(
        self,
        *,
        output_text: str,
        structured_aliases: dict[str, tuple[str, ...]],
    ) -> dict[str, Any]:
        parsed: dict[str, Any] = {key: "" for key in structured_aliases}
        parsed_json = self._parse_structured_output_json(
            output_text=output_text,
            structured_aliases=structured_aliases,
        )
        if parsed_json:
            parsed.update(parsed_json)
            return parsed
        current_field: str | None = None
        for raw_line in str(output_text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue

            normalized_line = self._strip_list_prefix(line)
            label_and_value = self._split_label_and_value(normalized_line)
            if label_and_value is not None:
                label_raw, value_raw = label_and_value
                matched_field = self._resolve_structured_output_field(
                    label_raw,
                    structured_aliases=structured_aliases,
                )
                if matched_field is not None:
                    parsed[matched_field] = value_raw.strip()
                    current_field = matched_field
                    continue

            if current_field is not None:
                previous_value = str(parsed.get(current_field) or "").strip()
                parsed[current_field] = (
                    f"{previous_value}\n{line}".strip()
                    if previous_value
                    else line
                )
        return parsed

    def inspect_structured_output_json(
        self,
        *,
        output_text: str,
        structured_aliases: Mapping[str, Iterable[str]],
    ) -> dict[str, Any]:
        aliases = self._normalize_aliases(structured_aliases)
        raw_output = str(output_text or "").strip()
        if not raw_output:
            return {
                "cleaned_payload": None,
                "parsed_json": None,
                "mapped_fields": {},
                "parse_error": None,
            }

        candidates = self._build_json_candidates(raw_output)
        last_error: str | None = None
        for candidate in candidates:
            cleaned_candidate = str(candidate or "").strip()
            if not cleaned_candidate:
                continue
            try:
                loaded = json.loads(cleaned_candidate)
            except Exception as exc:
                last_error = str(exc)
                continue

            payload = self._coerce_json_payload_object(loaded)
            if payload is None:
                last_error = "JSON payload must be an object or list with object."
                continue
            return {
                "cleaned_payload": cleaned_candidate,
                "parsed_json": payload,
                "mapped_fields": self._map_json_payload_to_fields(payload=payload, structured_aliases=aliases),
                "parse_error": None,
            }

        return {
            "cleaned_payload": candidates[0] if candidates else None,
            "parsed_json": None,
            "mapped_fields": {},
            "parse_error": last_error,
        }

    def _parse_structured_output_json(
        self,
        *,
        output_text: str,
        structured_aliases: dict[str, tuple[str, ...]],
    ) -> dict[str, Any]:
        inspection = self.inspect_structured_output_json(
            output_text=output_text,
            structured_aliases=structured_aliases,
        )
        mapped_fields = inspection.get("mapped_fields")
        if isinstance(mapped_fields, dict):
            return mapped_fields
        return {}

    @staticmethod
    def _coerce_json_payload_object(loaded: Any) -> dict[str, Any] | None:
        if isinstance(loaded, dict):
            return loaded
        if isinstance(loaded, list):
            if loaded and isinstance(loaded[0], dict):
                return loaded[0]
        return None

    def _map_json_payload_to_fields(
        self,
        *,
        payload: dict[str, Any],
        structured_aliases: dict[str, tuple[str, ...]],
    ) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for raw_key, raw_value in payload.items():
            field = self._resolve_structured_output_field(str(raw_key), structured_aliases=structured_aliases)
            if field is None:
                continue
            parsed[field] = raw_value
        return parsed

    def _build_json_candidates(self, raw_output: str) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()

        def _append(value: str | None) -> None:
            token = str(value or "").strip()
            if not token or token in seen:
                return
            seen.add(token)
            candidates.append(token)

        for block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw_output, flags=re.IGNORECASE):
            _append(block)
        _append(raw_output)
        _append(self._extract_balanced_json_fragment(raw_output))
        return candidates

    @staticmethod
    def _extract_balanced_json_fragment(raw_output: str) -> str | None:
        raw = str(raw_output or "")
        if not raw:
            return None
        start = -1
        for index, token in enumerate(raw):
            if token in "{[":
                start = index
                break
        if start < 0:
            return None

        expected_stack: list[str] = []
        string_mode = False
        escaped = False
        for index in range(start, len(raw)):
            token = raw[index]
            if string_mode:
                if escaped:
                    escaped = False
                elif token == "\\":
                    escaped = True
                elif token == '"':
                    string_mode = False
                continue

            if token == '"':
                string_mode = True
                continue
            if token == "{":
                expected_stack.append("}")
                continue
            if token == "[":
                expected_stack.append("]")
                continue
            if token in {"}", "]"}:
                if not expected_stack or token != expected_stack[-1]:
                    return None
                expected_stack.pop()
                if not expected_stack:
                    return raw[start : index + 1].strip()
        return None

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

    def _resolve_structured_output_field(
        self,
        label_raw: str,
        *,
        structured_aliases: dict[str, tuple[str, ...]],
    ) -> str | None:
        label_key = self._normalize_key(label_raw).replace("_", " ")
        if not label_key:
            return None
        for field_name, aliases in structured_aliases.items():
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
