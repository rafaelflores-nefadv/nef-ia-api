from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from uuid import UUID

from app.core.exceptions import AppException
from app.services.execution_engine import (
    ExecutionFormatterStrategy,
    ExecutionInputType,
    ExecutionOutputContract,
    ExecutionOutputSchema,
    ExecutionOutputType,
    ExecutionParserStrategy,
    build_default_text_output_contract,
    build_legacy_tabular_output_contract,
)


class ExecutionOutputContractResolver:
    def resolve(
        self,
        *,
        input_type: ExecutionInputType,
        automation_id: UUID | None = None,
        automation_slug: str | None = None,
        runtime_output_type: str | None = None,
        runtime_result_parser: str | None = None,
        runtime_result_formatter: str | None = None,
        runtime_output_schema: dict[str, Any] | str | None = None,
    ) -> ExecutionOutputContract:
        default_contract = self._default_contract_for_input_type(input_type=input_type)
        has_explicit_contract = any(
            value is not None
            for value in (
                runtime_output_type,
                runtime_result_parser,
                runtime_result_formatter,
                runtime_output_schema,
            )
        )
        if not has_explicit_contract:
            return ExecutionOutputContract(
                output_type=default_contract.output_type,
                parser_strategy=default_contract.parser_strategy,
                formatter_strategy=default_contract.formatter_strategy,
                output_schema=default_contract.output_schema,
                source="fallback_no_output_contract_config",
                source_details={
                    "automation_id": str(automation_id) if automation_id else None,
                    "automation_slug": str(automation_slug or "").strip() or None,
                },
            )

        output_type = default_contract.output_type
        if runtime_output_type is not None:
            output_type = self._coerce_output_type(runtime_output_type, strict=True)

        parser_strategy = default_contract.parser_strategy
        if runtime_result_parser is not None:
            parser_strategy = self._coerce_parser_strategy(runtime_result_parser, strict=True)

        formatter_strategy = default_contract.formatter_strategy
        if runtime_result_formatter is not None:
            formatter_strategy = self._coerce_formatter_strategy(runtime_result_formatter, strict=True)

        schema_overrides = self._parse_output_schema_payload(
            runtime_output_schema,
            strict=runtime_output_schema is not None,
        )

        output_schema = self._merge_schema(
            default_schema=default_contract.output_schema,
            overrides=schema_overrides,
            strict=runtime_output_schema is not None,
        )
        resolved_contract = ExecutionOutputContract(
            output_type=output_type,
            parser_strategy=parser_strategy,
            formatter_strategy=formatter_strategy,
            output_schema=output_schema,
            source="automation_output_contract",
            source_details={
                "automation_id": str(automation_id) if automation_id else None,
                "automation_slug": str(automation_slug or "").strip() or None,
            },
        )
        self._validate_contract_compatibility(
            input_type=input_type,
            contract=resolved_contract,
        )
        return resolved_contract

    @staticmethod
    def _default_contract_for_input_type(*, input_type: ExecutionInputType) -> ExecutionOutputContract:
        if input_type in {ExecutionInputType.TABULAR, ExecutionInputType.TABULAR_WITH_CONTEXT}:
            return build_legacy_tabular_output_contract()
        return build_default_text_output_contract()

    @staticmethod
    def _parse_output_schema_payload(
        payload: dict[str, Any] | str | None,
        *,
        strict: bool,
    ) -> dict[str, Any]:
        if payload is None:
            return {}
        if isinstance(payload, dict):
            return payload
        raw = str(payload or "").strip()
        if not raw:
            if strict:
                raise AppException(
                    "Output schema is invalid: empty schema payload.",
                    status_code=422,
                    code="execution_output_schema_invalid",
                )
            return {}
        try:
            loaded = json.loads(raw)
        except Exception as exc:
            raise AppException(
                "Output schema is invalid: malformed JSON payload.",
                status_code=422,
                code="execution_output_schema_invalid",
                details={"payload_type": type(payload).__name__},
            ) from exc
        if not isinstance(loaded, dict):
            raise AppException(
                "Output schema is invalid: expected a JSON object.",
                status_code=422,
                code="execution_output_schema_invalid",
                details={"payload_type": type(loaded).__name__},
            )
        return loaded

    @staticmethod
    def _coerce_output_type(raw_value: str | None, *, strict: bool = False) -> ExecutionOutputType | None:
        normalized = str(raw_value or "").strip().lower()
        if not normalized:
            if strict:
                raise AppException(
                    "Output contract is invalid: output_type is empty.",
                    status_code=422,
                    code="execution_output_contract_invalid",
                )
            return None
        aliases = {
            "text": ExecutionOutputType.TEXT_OUTPUT,
            "text_raw": ExecutionOutputType.TEXT_OUTPUT,
            "plain_text": ExecutionOutputType.TEXT_OUTPUT,
            "text_output": ExecutionOutputType.TEXT_OUTPUT,
            "spreadsheet": ExecutionOutputType.SPREADSHEET_OUTPUT,
            "spreadsheet_output": ExecutionOutputType.SPREADSHEET_OUTPUT,
            "xlsx": ExecutionOutputType.SPREADSHEET_OUTPUT,
            "excel": ExecutionOutputType.SPREADSHEET_OUTPUT,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return ExecutionOutputType(normalized)
        except ValueError:
            if strict:
                raise AppException(
                    "Output contract is invalid: unsupported output_type.",
                    status_code=422,
                    code="execution_output_contract_invalid",
                    details={"output_type": raw_value},
                )
            return None

    @staticmethod
    def _coerce_parser_strategy(
        raw_value: str | None,
        *,
        strict: bool = False,
    ) -> ExecutionParserStrategy | None:
        normalized = str(raw_value or "").strip().lower()
        if not normalized:
            if strict:
                raise AppException(
                    "Output contract is invalid: result_parser is empty.",
                    status_code=422,
                    code="execution_output_contract_invalid",
                )
            return None
        aliases = {
            "text": ExecutionParserStrategy.TEXT_RAW,
            "text_raw": ExecutionParserStrategy.TEXT_RAW,
            "raw": ExecutionParserStrategy.TEXT_RAW,
            "tabular_structured": ExecutionParserStrategy.TABULAR_STRUCTURED,
            "structured_tabular": ExecutionParserStrategy.TABULAR_STRUCTURED,
            "structured": ExecutionParserStrategy.TABULAR_STRUCTURED,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return ExecutionParserStrategy(normalized)
        except ValueError:
            if strict:
                raise AppException(
                    "Output contract is invalid: unsupported result_parser.",
                    status_code=422,
                    code="execution_output_contract_invalid",
                    details={"result_parser": raw_value},
                )
            return None

    @staticmethod
    def _coerce_formatter_strategy(
        raw_value: str | None,
        *,
        strict: bool = False,
    ) -> ExecutionFormatterStrategy | None:
        normalized = str(raw_value or "").strip().lower()
        if not normalized:
            if strict:
                raise AppException(
                    "Output contract is invalid: result_formatter is empty.",
                    status_code=422,
                    code="execution_output_contract_invalid",
                )
            return None
        aliases = {
            "text": ExecutionFormatterStrategy.TEXT_PLAIN,
            "text_plain": ExecutionFormatterStrategy.TEXT_PLAIN,
            "plain_text": ExecutionFormatterStrategy.TEXT_PLAIN,
            "spreadsheet": ExecutionFormatterStrategy.SPREADSHEET_TABULAR,
            "spreadsheet_tabular": ExecutionFormatterStrategy.SPREADSHEET_TABULAR,
            "tabular_spreadsheet": ExecutionFormatterStrategy.SPREADSHEET_TABULAR,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return ExecutionFormatterStrategy(normalized)
        except ValueError:
            if strict:
                raise AppException(
                    "Output contract is invalid: unsupported result_formatter.",
                    status_code=422,
                    code="execution_output_contract_invalid",
                    details={"result_formatter": raw_value},
                )
            return None

    def _merge_schema(
        self,
        *,
        default_schema: ExecutionOutputSchema,
        overrides: dict[str, Any],
        strict: bool,
    ) -> ExecutionOutputSchema:
        has_explicit_columns = "columns" in overrides or "output_columns" in overrides
        raw_columns = (
            overrides.get("columns")
            if "columns" in overrides
            else overrides.get("output_columns")
        )
        columns = self._coerce_columns(
            raw_columns,
            fallback=default_schema.columns,
            strict=strict and has_explicit_columns,
        )
        structured_output_aliases = self._coerce_structured_aliases(
            overrides.get("structured_output_aliases"),
            fallback=default_schema.structured_output_aliases,
            strict=strict and "structured_output_aliases" in overrides,
        )
        ai_output_columns = self._coerce_columns(
            overrides.get("ai_output_columns"),
            fallback=default_schema.ai_output_columns,
            strict=strict and "ai_output_columns" in overrides,
        )
        include_input_columns = self._coerce_bool(
            value=overrides.get("include_input_columns"),
            fallback=default_schema.include_input_columns,
            strict=strict and "include_input_columns" in overrides,
            field_name="include_input_columns",
        )
        if strict and has_explicit_columns and "include_input_columns" not in overrides:
            include_input_columns = False

        status_fallback = default_schema.status_column
        error_fallback = default_schema.error_column
        if strict and "status_column" not in overrides:
            status_fallback = None
        if strict and "error_column" not in overrides:
            error_fallback = None

        status_column = self._coerce_optional_column_name(
            overrides=overrides,
            key="status_column",
            fallback=status_fallback,
            strict=strict,
        )
        error_column = self._coerce_optional_column_name(
            overrides=overrides,
            key="error_column",
            fallback=error_fallback,
            strict=strict,
        )

        row_origin_fallback = default_schema.row_origin_column
        if strict and "row_origin_column" not in overrides and not include_input_columns:
            row_origin_fallback = None
        row_origin_column = self._coerce_optional_column_name(
            overrides=overrides,
            key="row_origin_column",
            fallback=row_origin_fallback,
            strict=strict,
        )

        prompt_field_columns = self._coerce_prompt_field_columns(
            overrides.get("prompt_field_columns"),
            fallback=default_schema.prompt_field_columns,
            strict=strict and "prompt_field_columns" in overrides,
        )
        input_column_mappings = self._coerce_input_column_mappings(
            overrides.get("input_column_mappings"),
            prompt_field_columns=prompt_field_columns,
            columns=columns,
            ai_output_columns=ai_output_columns,
            strict=strict and "input_column_mappings" in overrides,
        )
        if strict and has_explicit_columns and "prompt_field_columns" not in overrides:
            reserved_columns = {
                column
                for column in (row_origin_column, status_column, error_column)
                if column
            }
            inferred_input_columns = [
                column
                for column in columns
                if column not in set(ai_output_columns) and column not in reserved_columns
            ]
            prompt_field_columns = {column: column for column in inferred_input_columns}
            if input_column_mappings:
                input_column_mappings = self._coerce_input_column_mappings(
                    overrides.get("input_column_mappings"),
                    prompt_field_columns=prompt_field_columns,
                    columns=columns,
                    ai_output_columns=ai_output_columns,
                    strict=strict and "input_column_mappings" in overrides,
                )

        prompt_field_aliases = self._coerce_structured_aliases(
            overrides.get("prompt_field_aliases"),
            fallback=default_schema.prompt_field_aliases,
            strict=strict and "prompt_field_aliases" in overrides,
        )
        if input_column_mappings:
            prompt_field_aliases = self._merge_alias_maps(
                base=prompt_field_aliases,
                overrides=input_column_mappings,
            )
            for field_name in input_column_mappings:
                prompt_field_columns.setdefault(field_name, field_name)
        prompt_placeholders = self._coerce_prompt_placeholders(
            overrides.get("prompt_placeholders"),
            fallback=default_schema.prompt_placeholders,
            strict=strict and "prompt_placeholders" in overrides,
        )
        merged_schema = ExecutionOutputSchema(
            columns=columns,
            structured_output_aliases=structured_output_aliases,
            prompt_field_columns=prompt_field_columns,
            prompt_field_aliases=prompt_field_aliases,
            prompt_placeholders=prompt_placeholders,
            ai_output_columns=ai_output_columns,
            row_origin_column=row_origin_column,
            status_column=status_column,
            error_column=error_column,
            include_input_columns=include_input_columns,
            input_collision_prefix=self._coerce_string(
                overrides.get("input_collision_prefix"),
                fallback=default_schema.input_collision_prefix,
                strict=strict and "input_collision_prefix" in overrides,
                field_name="input_collision_prefix",
            ),
            worksheet_name=self._coerce_string(
                overrides.get("worksheet_name"),
                fallback=default_schema.worksheet_name,
                strict=strict and "worksheet_name" in overrides,
                field_name="worksheet_name",
            ),
            file_name_template=self._coerce_optional_string(
                overrides.get("file_name_template"),
                fallback=default_schema.file_name_template,
                strict=strict and "file_name_template" in overrides,
                field_name="file_name_template",
            ),
            mime_type=self._coerce_optional_string(
                overrides.get("mime_type"),
                fallback=default_schema.mime_type,
                strict=strict and "mime_type" in overrides,
                field_name="mime_type",
            ),
        )
        self._validate_schema_structure(schema=merged_schema)
        return merged_schema

    @staticmethod
    def _coerce_columns(
        value: Any,
        *,
        fallback: tuple[str, ...],
        strict: bool,
    ) -> tuple[str, ...]:
        if value is None:
            return fallback
        if isinstance(value, str):
            candidates = [token.strip() for token in value.split(",")]
        elif isinstance(value, (list, tuple, set)):
            candidates = [str(token).strip() for token in value]
        else:
            if strict:
                raise AppException(
                    "Output schema is invalid: columns must be a list or comma-separated string.",
                    status_code=422,
                    code="execution_output_schema_invalid",
                )
            return fallback
        normalized = tuple(token for token in candidates if token)
        if strict and not normalized:
            raise AppException(
                "Output schema is invalid: columns cannot be empty.",
                status_code=422,
                code="execution_output_schema_invalid",
            )
        return normalized or fallback

    @staticmethod
    def _coerce_structured_aliases(
        value: Any,
        *,
        fallback: dict[str, tuple[str, ...]],
        strict: bool,
    ) -> dict[str, tuple[str, ...]]:
        if not isinstance(value, dict):
            if strict:
                raise AppException(
                    "Output schema is invalid: alias map must be an object.",
                    status_code=422,
                    code="execution_output_schema_invalid",
                )
            return fallback
        parsed: dict[str, tuple[str, ...]] = {}
        for field_name, aliases in value.items():
            normalized_field = str(field_name or "").strip()
            if not normalized_field:
                continue
            alias_values: list[str]
            if isinstance(aliases, str):
                alias_values = [aliases.strip()]
            elif isinstance(aliases, (list, tuple, set)):
                alias_values = [str(alias).strip() for alias in aliases]
            else:
                alias_values = []
            deduped = tuple(dict.fromkeys(alias for alias in alias_values if alias))
            if deduped:
                parsed[normalized_field] = deduped
        if strict and not parsed:
            raise AppException(
                "Output schema is invalid: alias map cannot be empty.",
                status_code=422,
                code="execution_output_schema_invalid",
            )
        return parsed or fallback

    @staticmethod
    def _merge_alias_maps(
        *,
        base: dict[str, tuple[str, ...]],
        overrides: dict[str, tuple[str, ...]],
    ) -> dict[str, tuple[str, ...]]:
        merged: dict[str, tuple[str, ...]] = {key: tuple(value) for key, value in base.items()}
        for field_name, aliases in overrides.items():
            existing = list(merged.get(field_name, ()))
            combined = tuple(dict.fromkeys([*aliases, *existing]))
            merged[field_name] = combined
        return merged

    @classmethod
    def _coerce_input_column_mappings(
        cls,
        value: Any,
        *,
        prompt_field_columns: dict[str, str],
        columns: tuple[str, ...],
        ai_output_columns: tuple[str, ...],
        strict: bool,
    ) -> dict[str, tuple[str, ...]]:
        """
        Canonical semantics:
        - Preferred: {canonical_field: [input_header_aliases...]}
        - Legacy-compatible: {input_header_alias: canonical_field}
        """
        if value is None:
            return {}
        if not isinstance(value, dict):
            if strict:
                raise AppException(
                    "Output schema is invalid: input_column_mappings must be an object.",
                    status_code=422,
                    code="execution_output_schema_invalid",
                )
            return {}

        collected: dict[str, list[str]] = {}
        unresolved_entries: list[dict[str, Any]] = []
        for raw_key, raw_value in value.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            value_tokens = cls._coerce_mapping_tokens(raw_value)

            # Preferred orientation: canonical_field -> aliases
            target_from_key = cls._resolve_mapping_target_field(
                key,
                prompt_field_columns=prompt_field_columns,
                columns=columns,
                ai_output_columns=ai_output_columns,
                allow_loose_normalization=False,
            )
            if target_from_key is not None and value_tokens:
                collected.setdefault(target_from_key, []).extend(value_tokens)
                continue

            # Legacy-compatible orientation: input_alias -> canonical_field
            resolved_targets = [
                target
                for target in (
                    cls._resolve_mapping_target_field(
                        candidate,
                        prompt_field_columns=prompt_field_columns,
                        columns=columns,
                        ai_output_columns=ai_output_columns,
                        allow_loose_normalization=True,
                    )
                    for candidate in value_tokens
                )
                if target is not None
            ]
            if resolved_targets:
                for target in resolved_targets:
                    collected.setdefault(target, []).append(key)
                continue

            unresolved_entries.append({"key": key, "value_type": type(raw_value).__name__})

        parsed: dict[str, tuple[str, ...]] = {}
        for field_name, aliases in collected.items():
            deduped = tuple(dict.fromkeys(alias for alias in aliases if str(alias).strip()))
            if deduped:
                parsed[field_name] = deduped

        if strict and unresolved_entries:
            raise AppException(
                "Output schema is invalid: input_column_mappings has entries with unresolved targets.",
                status_code=422,
                code="execution_output_schema_invalid",
                details={"unresolved_mappings": unresolved_entries},
            )
        if strict and not parsed:
            raise AppException(
                "Output schema is invalid: input_column_mappings cannot be empty.",
                status_code=422,
                code="execution_output_schema_invalid",
            )
        return parsed

    @classmethod
    def _resolve_mapping_target_field(
        cls,
        candidate: str,
        *,
        prompt_field_columns: dict[str, str],
        columns: tuple[str, ...],
        ai_output_columns: tuple[str, ...],
        allow_loose_normalization: bool,
    ) -> str | None:
        raw_candidate = str(candidate or "").strip()
        if not raw_candidate:
            return None
        normalized_candidate = cls._normalize_mapping_identifier(raw_candidate)
        if not normalized_candidate:
            return None

        # Canonical matching first, with exact comparison to avoid
        # misreading source headers as canonical targets.
        lowered_candidate = raw_candidate.casefold()
        for field_name in prompt_field_columns:
            if str(field_name).strip().casefold() == lowered_candidate:
                return field_name

        for field_name, column_name in prompt_field_columns.items():
            if str(column_name).strip().casefold() == lowered_candidate:
                return field_name

        ai_columns_raw = {str(column).strip().casefold() for column in ai_output_columns}
        for column_name in columns:
            lowered_column = str(column_name).strip().casefold()
            if lowered_column == lowered_candidate and lowered_column not in ai_columns_raw:
                return column_name

        if not allow_loose_normalization:
            return None

        for field_name in prompt_field_columns:
            if cls._normalize_mapping_identifier(field_name) == normalized_candidate:
                return field_name

        for field_name, column_name in prompt_field_columns.items():
            if cls._normalize_mapping_identifier(column_name) == normalized_candidate:
                return field_name

        ai_columns_normalized = {cls._normalize_mapping_identifier(column) for column in ai_output_columns}
        for column_name in columns:
            normalized_column = cls._normalize_mapping_identifier(column_name)
            if normalized_column == normalized_candidate and normalized_column not in ai_columns_normalized:
                return column_name
        return None

    @staticmethod
    def _coerce_mapping_tokens(value: Any) -> list[str]:
        if isinstance(value, str):
            tokens = [value]
        elif isinstance(value, (list, tuple, set)):
            tokens = [str(item) for item in value]
        else:
            tokens = []
        return [str(token).strip() for token in tokens if str(token).strip()]

    @staticmethod
    def _normalize_mapping_identifier(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        normalized = unicodedata.normalize("NFKD", raw)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
        return normalized

    @staticmethod
    def _coerce_prompt_field_columns(
        value: Any,
        *,
        fallback: dict[str, str],
        strict: bool,
    ) -> dict[str, str]:
        if not isinstance(value, dict):
            if strict:
                raise AppException(
                    "Output schema is invalid: prompt_field_columns must be an object.",
                    status_code=422,
                    code="execution_output_schema_invalid",
                )
            return fallback
        parsed: dict[str, str] = {}
        for field_name, column_name in value.items():
            normalized_field = str(field_name or "").strip()
            normalized_column = str(column_name or "").strip()
            if normalized_field and normalized_column:
                parsed[normalized_field] = normalized_column
        if strict and not parsed:
            raise AppException(
                "Output schema is invalid: prompt_field_columns cannot be empty.",
                status_code=422,
                code="execution_output_schema_invalid",
            )
        return parsed or fallback

    @staticmethod
    def _coerce_prompt_placeholders(
        value: Any,
        *,
        fallback: dict[str, str],
        strict: bool,
    ) -> dict[str, str]:
        if not isinstance(value, dict):
            if strict:
                raise AppException(
                    "Output schema is invalid: prompt_placeholders must be an object.",
                    status_code=422,
                    code="execution_output_schema_invalid",
                )
            return fallback
        parsed: dict[str, str] = {}
        for field_name, placeholder in value.items():
            normalized_field = str(field_name or "").strip()
            normalized_placeholder = str(placeholder or "").strip()
            if normalized_field and normalized_placeholder:
                parsed[normalized_field] = normalized_placeholder
        if strict and not parsed:
            raise AppException(
                "Output schema is invalid: prompt_placeholders cannot be empty.",
                status_code=422,
                code="execution_output_schema_invalid",
            )
        return parsed or fallback

    @staticmethod
    def _coerce_bool(
        *,
        value: Any,
        fallback: bool,
        strict: bool,
        field_name: str,
    ) -> bool:
        if value is None:
            return fallback
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        truthy = {"1", "true", "yes", "y", "on"}
        falsy = {"0", "false", "no", "n", "off"}
        if normalized in truthy:
            return True
        if normalized in falsy:
            return False
        if strict:
            raise AppException(
                f"Output schema is invalid: {field_name} must be a boolean.",
                status_code=422,
                code="execution_output_schema_invalid",
                details={"field_name": field_name, "value": value},
            )
        return fallback

    @staticmethod
    def _coerce_string(
        value: Any,
        *,
        fallback: str,
        strict: bool,
        field_name: str,
    ) -> str:
        normalized = str(value or "").strip()
        if strict and not normalized:
            raise AppException(
                f"Output schema is invalid: {field_name} cannot be empty.",
                status_code=422,
                code="execution_output_schema_invalid",
                details={"field_name": field_name},
            )
        return normalized or fallback

    @classmethod
    def _coerce_optional_column_name(
        cls,
        *,
        overrides: dict[str, Any],
        key: str,
        fallback: str | None,
        strict: bool,
    ) -> str | None:
        if key not in overrides:
            return fallback
        value = overrides.get(key)
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            if strict:
                raise AppException(
                    f"Output schema is invalid: {key} cannot be empty when provided.",
                    status_code=422,
                    code="execution_output_schema_invalid",
                    details={"field_name": key},
                )
            return fallback
        return normalized

    @staticmethod
    def _coerce_optional_string(
        value: Any,
        *,
        fallback: str | None,
        strict: bool,
        field_name: str,
    ) -> str | None:
        if value is None:
            return fallback
        normalized = str(value or "").strip()
        if strict and not normalized:
            raise AppException(
                f"Output schema is invalid: {field_name} cannot be empty when provided.",
                status_code=422,
                code="execution_output_schema_invalid",
                details={"field_name": field_name},
            )
        return normalized or fallback

    @staticmethod
    def _validate_schema_structure(*, schema: ExecutionOutputSchema) -> None:
        duplicates = {
            column
            for column in schema.columns
            if schema.columns.count(column) > 1
        }
        if duplicates:
            raise AppException(
                "Output schema is invalid: duplicate columns are not allowed.",
                status_code=422,
                code="execution_output_schema_invalid",
                details={"duplicate_columns": sorted(duplicates)},
            )

        if schema.ai_output_columns:
            unknown_ai_columns = sorted(
                column for column in schema.ai_output_columns if column not in set(schema.columns)
            )
            if unknown_ai_columns:
                raise AppException(
                    "Output schema is invalid: ai_output_columns must exist in columns.",
                    status_code=422,
                    code="execution_output_schema_invalid",
                    details={"unknown_ai_columns": unknown_ai_columns},
                )

        if schema.status_column and schema.error_column and schema.status_column == schema.error_column:
            raise AppException(
                "Output schema is invalid: status_column and error_column must be different.",
                status_code=422,
                code="execution_output_schema_invalid",
                details={"status_column": schema.status_column, "error_column": schema.error_column},
            )

        if schema.row_origin_column and schema.status_column and schema.status_column == schema.row_origin_column:
            raise AppException(
                "Output schema is invalid: status_column cannot collide with row_origin_column.",
                status_code=422,
                code="execution_output_schema_invalid",
                details={"status_column": schema.status_column, "row_origin_column": schema.row_origin_column},
            )

        if schema.row_origin_column and schema.error_column and schema.error_column == schema.row_origin_column:
            raise AppException(
                "Output schema is invalid: error_column cannot collide with row_origin_column.",
                status_code=422,
                code="execution_output_schema_invalid",
                details={"error_column": schema.error_column, "row_origin_column": schema.row_origin_column},
            )

    @staticmethod
    def _validate_contract_compatibility(
        *,
        input_type: ExecutionInputType,
        contract: ExecutionOutputContract,
    ) -> None:
        if input_type in {ExecutionInputType.TABULAR, ExecutionInputType.TABULAR_WITH_CONTEXT}:
            expected = (
                contract.output_type == ExecutionOutputType.SPREADSHEET_OUTPUT
                and contract.parser_strategy == ExecutionParserStrategy.TABULAR_STRUCTURED
                and contract.formatter_strategy == ExecutionFormatterStrategy.SPREADSHEET_TABULAR
            )
            if not expected:
                raise AppException(
                    "Output contract is incompatible with tabular input processing.",
                    status_code=422,
                    code="execution_output_contract_incompatible",
                    details={
                        "input_type": input_type.value,
                        "output_type": contract.output_type.value,
                        "result_parser": contract.parser_strategy.value,
                        "result_formatter": contract.formatter_strategy.value,
                    },
                )
            return

        if input_type in {ExecutionInputType.TEXT, ExecutionInputType.MULTI_TEXT}:
            expected = (
                contract.output_type == ExecutionOutputType.TEXT_OUTPUT
                and contract.parser_strategy == ExecutionParserStrategy.TEXT_RAW
                and contract.formatter_strategy == ExecutionFormatterStrategy.TEXT_PLAIN
            )
            if not expected:
                raise AppException(
                    "Output contract is incompatible with textual input processing.",
                    status_code=422,
                    code="execution_output_contract_incompatible",
                    details={
                        "input_type": input_type.value,
                        "output_type": contract.output_type.value,
                        "result_parser": contract.parser_strategy.value,
                        "result_formatter": contract.formatter_strategy.value,
                    },
                )
