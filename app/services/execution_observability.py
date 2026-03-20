from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.exceptions import AppException
from app.services.execution_engine import EngineExecutionInput, EngineExecutionPlan


@dataclass(slots=True)
class ExecutionErrorDiagnostic:
    message: str
    error_code: str
    error_category: str
    failure_phase: str


_ERROR_CATEGORY_RULES: tuple[tuple[set[str], str], ...] = (
    (
        {
            "execution_input_role_invalid",
            "execution_primary_input_invalid",
            "execution_input_type_unsupported",
            "multiple_tabular_inputs_not_supported",
            "tabular_primary_required",
            "tabular_context_type_invalid",
            "invalid_execution_input_combination",
            "execution_input_missing",
            "execution_input_item_invalid",
            "execution_input_duplicate_file",
            "execution_input_order_invalid",
            "execution_input_payload_conflict",
            "execution_input_primary_conflict",
            "execution_input_multiple_primary",
            "queue_job_request_file_missing",
        },
        "input_structure",
    ),
    (
        {
            "tabular_file_parse_error",
            "tabular_file_header_missing",
            "tabular_file_duplicate_headers",
            "tabular_file_without_rows",
            "unsupported_tabular_extension",
            "xls_legacy_not_supported",
            "request_file_not_found",
            "request_file_analysis_mismatch",
        },
        "input_read_parse",
    ),
    (
        {
            "provider_timeout",
            "provider_network_error",
            "provider_http_error",
            "provider_inactive",
            "provider_not_found",
            "provider_model_not_found",
            "provider_credential_not_found",
        },
        "provider",
    ),
    (
        {
            "execution_parser_strategy_invalid",
            "tabular_parser_invalid_output",
        },
        "response_parse",
    ),
    (
        {
            "cost_limit_exceeded",
            "prompt_token_limit_exceeded",
            "execution_rows_profile_limit_exceeded",
            "provider_calls_profile_limit_exceeded",
            "text_chunks_profile_limit_exceeded",
            "tabular_row_size_profile_limit_exceeded",
            "execution_time_profile_limit_exceeded",
            "execution_rows_hard_limit_exceeded",
            "provider_calls_hard_limit_exceeded",
            "text_chunks_hard_limit_exceeded",
            "tabular_row_size_hard_limit_exceeded",
            "execution_time_hard_limit_exceeded",
            "job_retries_hard_limit_exceeded",
        },
        "system_limit",
    ),
    (
        {
            "file_persist_failed",
            "file_missing_in_storage",
            "file_storage_mismatch",
            "analysis_execution_not_found",
        },
        "output_storage",
    ),
    (
        {
            "queue_enqueue_failed",
            "queue_job_not_found",
            "queue_job_execution_mismatch",
            "analysis_request_not_found",
            "execution_not_found",
            "execution_profile_resolution_failed",
        },
        "orchestration",
    ),
)


def summarize_processing_inputs(inputs: list[EngineExecutionInput]) -> dict[str, Any]:
    roles = sorted({item.role for item in inputs})
    kinds = sorted({item.file_kind.value for item in inputs})
    return {
        "input_file_count": len(inputs),
        "roles": {role: sum(1 for current in inputs if current.role == role) for role in roles},
        "kinds": {kind: sum(1 for current in inputs if current.file_kind.value == kind) for kind in kinds},
        "sources": sorted({item.source for item in inputs}),
        "inputs": [
            {
                "request_file_id": str(item.request_file_id),
                "role": item.role,
                "kind": item.file_kind.value,
                "order_index": item.order_index,
                "extension": Path(item.file_name).suffix.lower(),
            }
            for item in sorted(inputs, key=lambda entry: entry.order_index)
        ],
    }


def summarize_processing_plan(plan: EngineExecutionPlan) -> dict[str, Any]:
    return {
        "input_type": plan.input_type.value,
        "processing_mode": plan.processing_mode.value,
        "output_type": plan.output_type.value,
        "parser_strategy": plan.parser_strategy.value,
        "primary_request_file_id": str(plan.primary_input.request_file_id),
        "input_file_count": len(plan.ordered_inputs),
        "context_file_count": len(plan.context_inputs),
    }


def classify_execution_error(exc: Exception, *, failure_phase: str) -> ExecutionErrorDiagnostic:
    if isinstance(exc, AppException):
        error_code = exc.payload.code or "application_error"
        message = exc.payload.message
    else:
        error_code = "unexpected_error"
        message = str(exc)

    category = "unexpected"
    for codes, mapped_category in _ERROR_CATEGORY_RULES:
        if error_code in codes:
            category = mapped_category
            break

    return ExecutionErrorDiagnostic(
        message=message,
        error_code=error_code,
        error_category=category,
        failure_phase=failure_phase,
    )
