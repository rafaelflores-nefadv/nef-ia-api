from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.core.exceptions import AppException
from app.services.execution_engine import ExecutionOutputSchema


@dataclass(slots=True, frozen=True)
class TabularPromptFieldResolution:
    values: dict[str, str]
    sources: dict[str, str]


@dataclass(slots=True, frozen=True)
class TabularPromptRenderResult:
    prompt_text: str
    detected_placeholders: tuple[str, ...]
    resolved_placeholders: tuple[str, ...]
    unresolved_placeholders: tuple[str, ...]
    row_data: dict[str, str]
    field_sources: dict[str, str]


@dataclass(slots=True, frozen=True)
class TabularPromptStrategy:
    field_aliases: dict[str, tuple[str, ...]]
    placeholders: dict[str, str]
    field_order: tuple[str, ...]

    @staticmethod
    def _normalize_key(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        normalized = unicodedata.normalize("NFKD", raw)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
        return normalized

    def resolve_prompt_fields(self, *, row_values: dict[str, Any]) -> TabularPromptFieldResolution:
        indexed: dict[str, tuple[str, str]] = {}
        for raw_key, raw_value in row_values.items():
            normalized_key = self._normalize_key(raw_key)
            if not normalized_key:
                continue
            normalized_value = str(raw_value or "").strip()
            source_key = str(raw_key or "").strip()
            existing = indexed.get(normalized_key)
            if existing is None or (not existing[1] and normalized_value):
                indexed[normalized_key] = (source_key, normalized_value)

        resolved: dict[str, str] = {}
        sources: dict[str, str] = {}
        for field_name in self.field_order:
            aliases = self.field_aliases.get(field_name) or (field_name,)
            value = ""
            source_header = ""
            for alias in aliases:
                candidate = indexed.get(self._normalize_key(alias))
                if candidate and candidate[1]:
                    source_header = candidate[0]
                    value = candidate[1]
                    break
            resolved[field_name] = value
            if source_header:
                sources[field_name] = source_header

        # Legacy-compatible fallback: keep first mapped field populated when aliases don't match.
        if self.field_order:
            first_field = self.field_order[0]
            if not resolved.get(first_field):
                fallback = next((item for item in indexed.values() if item[1]), None)
                resolved[first_field] = fallback[1] if fallback is not None else ""
                if fallback is not None:
                    sources[first_field] = fallback[0]
        return TabularPromptFieldResolution(values=resolved, sources=sources)

    def extract_prompt_fields(self, *, row_values: dict[str, Any]) -> dict[str, str]:
        # Compatibility shim for existing call sites/tests.
        return self.resolve_prompt_fields(row_values=row_values).values

    def render_prompt(
        self,
        *,
        official_prompt: str,
        prompt_fields: dict[str, str],
        global_context: str | None,
        normalize_inline_text,
        assemble_prompt,
        execution_profile,
    ) -> str:  # type: ignore[no-untyped-def]
        return self.render_prompt_with_metadata(
            official_prompt=official_prompt,
            prompt_fields=prompt_fields,
            global_context=global_context,
            normalize_inline_text=normalize_inline_text,
            assemble_prompt=assemble_prompt,
            execution_profile=execution_profile,
        ).prompt_text

    def render_prompt_with_metadata(
        self,
        *,
        official_prompt: str,
        prompt_fields: dict[str, str],
        global_context: str | None,
        normalize_inline_text,
        assemble_prompt,
        execution_profile,
        field_sources: dict[str, str] | None = None,
    ) -> TabularPromptRenderResult:  # type: ignore[no-untyped-def]
        rendered = str(official_prompt or "")
        detected_placeholders = self._detect_placeholders(rendered)
        prompt_row_data: dict[str, str] = {}
        resolved_placeholder_values: dict[str, str] = {}
        field_sources = {str(key): str(value) for key, value in (field_sources or {}).items() if str(key).strip()}

        placeholder_value_index: dict[str, str] = {}
        placeholder_source_index: dict[str, str] = {}
        for field_name in self.field_order:
            normalized_value = normalize_inline_text(prompt_fields.get(field_name) or "")
            candidate_tokens = [
                str(self.placeholders.get(field_name) or "").strip(),
                field_name,
                *(self.field_aliases.get(field_name) or ()),
            ]
            for candidate_token in candidate_tokens:
                normalized_token = self._normalize_key(candidate_token)
                if not normalized_token:
                    continue
                current_value = placeholder_value_index.get(normalized_token, "")
                if current_value and not normalized_value:
                    continue
                placeholder_value_index[normalized_token] = normalized_value
                source_value = str(field_sources.get(field_name) or "").strip()
                if source_value:
                    placeholder_source_index[normalized_token] = source_value

        unresolved_placeholders: list[str] = []
        resolved_placeholders: list[str] = []
        if detected_placeholders:
            detected_placeholder_index = {self._normalize_key(item) for item in detected_placeholders}
            for placeholder in detected_placeholders:
                normalized_placeholder = self._normalize_key(placeholder)
                resolved_value = str(placeholder_value_index.get(normalized_placeholder) or "").strip()
                if not resolved_value:
                    unresolved_placeholders.append(placeholder)
                    continue
                pattern = re.compile(r"\{\{\s*" + re.escape(placeholder) + r"\s*\}\}", re.IGNORECASE)
                rendered = pattern.sub(resolved_value, rendered)
                resolved_placeholder_values[placeholder] = resolved_value
                resolved_placeholders.append(placeholder)

            # Preserve contextual row block only for fields not already represented
            # by explicit placeholders in the instruction text.
            for field_name in self.field_order:
                placeholder_token = str(self.placeholders.get(field_name) or "").strip() or field_name.upper()
                if self._normalize_key(placeholder_token) in detected_placeholder_index:
                    continue
                value = normalize_inline_text(prompt_fields.get(field_name) or "")
                if value:
                    prompt_row_data[placeholder_token] = value
        else:
            # Compatibility mode: prompts without placeholders still receive contextual row block.
            for field_name in self.field_order:
                placeholder = str(self.placeholders.get(field_name) or "").strip() or field_name.upper()
                value = normalize_inline_text(prompt_fields.get(field_name) or "")
                prompt_row_data[placeholder] = value

        if unresolved_placeholders:
            raise AppException(
                "Prompt hydration failed: unresolved placeholders in automation prompt.",
                status_code=422,
                code="prompt_placeholder_unresolved",
                details={
                    "unresolved_placeholders": unresolved_placeholders,
                    "detected_placeholders": list(detected_placeholders),
                    "resolved_placeholders": resolved_placeholders,
                    "field_sources": field_sources,
                },
            )

        contextual_block = ""
        if global_context:
            contextual_block = (
                "Contexto global complementar (aplicado em todas as linhas):\n"
                f"{global_context}"
            )

        prompt_text = assemble_prompt(
            instruction_text=rendered,
            row_data=prompt_row_data,
            auxiliary_context=contextual_block,
            execution_profile=execution_profile,
        )
        return TabularPromptRenderResult(
            prompt_text=prompt_text,
            detected_placeholders=detected_placeholders,
            resolved_placeholders=tuple(resolved_placeholders),
            unresolved_placeholders=tuple(unresolved_placeholders),
            row_data=resolved_placeholder_values if detected_placeholders else prompt_row_data,
            field_sources={
                placeholder: placeholder_source_index.get(self._normalize_key(placeholder), "")
                for placeholder in resolved_placeholders
            },
        )

    def detect_placeholders(self, prompt_text: str) -> tuple[str, ...]:
        return self._detect_placeholders(prompt_text)

    @staticmethod
    def _detect_placeholders(prompt_text: str) -> tuple[str, ...]:
        tokens = re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", str(prompt_text or ""))
        ordered = [str(token).strip() for token in tokens if str(token).strip()]
        return tuple(dict.fromkeys(ordered))


class TabularPromptStrategyResolver:
    def resolve(self, *, output_schema: ExecutionOutputSchema) -> TabularPromptStrategy:
        field_order = tuple(output_schema.prompt_field_columns.keys())
        if not field_order:
            field_order = ("conteudo",)

        field_aliases: dict[str, tuple[str, ...]] = {}
        for field_name in field_order:
            raw_aliases = output_schema.prompt_field_aliases.get(field_name)
            field_column = str(output_schema.prompt_field_columns.get(field_name) or "").strip()
            alias_candidates = list(raw_aliases or ())
            if field_column:
                alias_candidates.append(field_column)
            alias_candidates.append(field_name)
            normalized_aliases = tuple(dict.fromkeys(alias for alias in alias_candidates if str(alias).strip()))
            field_aliases[field_name] = normalized_aliases or (field_name,)

        placeholders: dict[str, str] = {}
        for field_name in field_order:
            explicit_placeholder = str(output_schema.prompt_placeholders.get(field_name) or "").strip()
            placeholders[field_name] = explicit_placeholder or field_name.upper()

        return TabularPromptStrategy(
            field_aliases=field_aliases,
            placeholders=placeholders,
            field_order=field_order,
        )
