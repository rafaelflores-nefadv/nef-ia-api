from __future__ import annotations

from typing import Any

OUTPUT_TYPE_LABELS: dict[str, str] = {
    "spreadsheet_output": "Planilha",
    "text_output": "Texto",
    "json_structured": "JSON estruturado",
}

RESULT_PARSER_LABELS: dict[str, str] = {
    "tabular_structured": "Tabular estruturado",
    "text_raw": "Texto bruto",
    "json_structured": "JSON estruturado",
}

RESULT_FORMATTER_LABELS: dict[str, str] = {
    "spreadsheet_tabular": "Planilha tabular",
    "text_plain": "Texto simples",
    "json_output": "Saida JSON",
}

OUTPUT_TYPE_CHOICES_PT: tuple[tuple[str, str], ...] = (
    ("spreadsheet_output", OUTPUT_TYPE_LABELS["spreadsheet_output"]),
    ("text_output", OUTPUT_TYPE_LABELS["text_output"]),
)

RESULT_PARSER_CHOICES_PT: tuple[tuple[str, str], ...] = (
    ("tabular_structured", RESULT_PARSER_LABELS["tabular_structured"]),
    ("text_raw", RESULT_PARSER_LABELS["text_raw"]),
)

RESULT_FORMATTER_CHOICES_PT: tuple[tuple[str, str], ...] = (
    ("spreadsheet_tabular", RESULT_FORMATTER_LABELS["spreadsheet_tabular"]),
    ("text_plain", RESULT_FORMATTER_LABELS["text_plain"]),
)

_COMPATIBILITY: dict[str, dict[str, set[str]]] = {
    "spreadsheet_output": {
        "result_parser": {"tabular_structured"},
        "result_formatter": {"spreadsheet_tabular"},
    },
    "text_output": {
        "result_parser": {"text_raw"},
        "result_formatter": {"text_plain"},
    },
}


def label_output_type(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "Padrao legado"
    return OUTPUT_TYPE_LABELS.get(normalized, normalized)


def label_result_parser(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "Padrao legado"
    return RESULT_PARSER_LABELS.get(normalized, normalized)


def label_result_formatter(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "Padrao legado"
    return RESULT_FORMATTER_LABELS.get(normalized, normalized)


def has_explicit_contract(
    *,
    output_type: str | None,
    result_parser: str | None,
    result_formatter: str | None,
    output_schema: dict[str, Any] | str | None,
) -> bool:
    if str(output_type or "").strip():
        return True
    if str(result_parser or "").strip():
        return True
    if str(result_formatter or "").strip():
        return True
    if isinstance(output_schema, dict):
        return bool(output_schema)
    if isinstance(output_schema, str):
        return bool(output_schema.strip())
    return False


def summarize_output_schema(output_schema: dict[str, Any] | str | None) -> str:
    if output_schema is None:
        return "Padrao legado"
    if isinstance(output_schema, str):
        raw = output_schema.strip()
        if not raw:
            return "Padrao legado"
        if len(raw) <= 80:
            return raw
        return f"{raw[:80]}..."
    if isinstance(output_schema, dict):
        if not output_schema:
            return "Padrao legado"
        keys = [str(key) for key in output_schema.keys()][:3]
        keys_display = ", ".join(keys)
        if len(output_schema) > 3:
            keys_display = f"{keys_display}, ..."
        return f"{len(output_schema)} chave(s): {keys_display}"
    return "Schema customizado"


def validate_contract_combination(
    *,
    output_type: str | None,
    result_parser: str | None,
    result_formatter: str | None,
    has_schema: bool,
) -> str | None:
    normalized_output = str(output_type or "").strip()
    normalized_parser = str(result_parser or "").strip()
    normalized_formatter = str(result_formatter or "").strip()

    provided_core = [bool(normalized_output), bool(normalized_parser), bool(normalized_formatter)]
    if any(provided_core) and not all(provided_core):
        return "Para contrato explicito, preencha tipo de saida, parser e formatador."

    if not any(provided_core):
        if has_schema:
            return "Defina tipo, parser e formatador para usar schema customizado."
        return None

    compatibility = _COMPATIBILITY.get(normalized_output)
    if compatibility is None:
        return "Tipo de saida nao suportado para este ambiente."

    allowed_parsers = compatibility["result_parser"]
    if normalized_parser not in allowed_parsers:
        return "Parser de resultado incompativel com o tipo de saida selecionado."

    allowed_formatters = compatibility["result_formatter"]
    if normalized_formatter not in allowed_formatters:
        return "Formatador de resultado incompativel com o tipo de saida selecionado."

    return None
