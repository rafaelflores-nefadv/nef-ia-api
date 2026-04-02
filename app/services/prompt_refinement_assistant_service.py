from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.services.external_catalog_service import ExternalCatalogService


COMPATIBILITY_READY = "ready_without_schema_changes"
COMPATIBILITY_SCHEMA_UPDATE = "ready_with_schema_update_required"
COMPATIBILITY_MANUAL_REVIEW = "needs_manual_review"
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"


@dataclass(slots=True)
class PromptRefinementPreviewResult:
    automation_id: uuid.UUID
    prompt_original: str | None
    prompt_received: str
    refined_prompt: str
    current_result_fields: list[str]
    suggested_result_fields: list[str]
    fields_to_add: list[str]
    fields_to_remove: list[str]
    proposed_output_schema: dict[str, Any] | None
    compatibility_status: str
    can_execute_now: bool
    action_required_message: str


@dataclass(slots=True)
class PromptRefinementApplyResult:
    automation_id: uuid.UUID
    automation_name: str
    automation_is_active: bool
    output_schema: dict[str, Any] | None
    prompt_update_applied: bool
    schema_update_applied: bool
    updated_prompt_id: uuid.UUID | None
    updated_prompt_version: int | None
    applied_prompt_text: str | None
    previous_result_fields: list[str]
    current_result_fields: list[str]
    suggested_result_fields: list[str]
    fields_added: list[str]
    fields_removed: list[str]
    can_execute_now: bool
    action_required_message: str
    change_summary: str


@dataclass(slots=True)
class PromptRefinementAdvancedPreviewResult:
    automation_id: uuid.UUID
    raw_prompt: str
    corrected_prompt: str
    prompt_original: str | None
    current_prompt_summary: str | None
    prompt_change_summary: str
    current_result_fields: list[str]
    suggested_result_fields: list[str]
    fields_to_add: list[str]
    fields_to_remove: list[str]
    current_output_schema: dict[str, Any] | None
    proposed_output_schema: dict[str, Any] | None
    schema_diff: dict[str, Any]
    placeholder_analysis: dict[str, Any]
    mapping_analysis: dict[str, Any]
    confidence_level: str
    compatibility_status: str
    can_execute_now: bool
    action_required_message: str
    review_recommendations: list[str]
    technical_warnings: list[str]
    safe_apply_options: dict[str, bool]


@dataclass(slots=True)
class PromptRefinementAdvancedApplyResult:
    automation_id: uuid.UUID
    automation_name: str
    automation_is_active: bool
    output_schema: dict[str, Any] | None
    prompt_update_applied: bool
    schema_update_applied: bool
    updated_prompt_id: uuid.UUID | None
    updated_prompt_version: int | None
    applied_prompt_text: str | None
    previous_result_fields: list[str]
    current_result_fields: list[str]
    suggested_result_fields: list[str]
    fields_added: list[str]
    fields_removed: list[str]
    current_output_schema: dict[str, Any] | None
    applied_output_schema: dict[str, Any] | None
    schema_diff: dict[str, Any]
    placeholder_analysis: dict[str, Any]
    mapping_analysis: dict[str, Any]
    confidence_level: str
    compatibility_status: str
    can_execute_now: bool
    action_required_message: str
    review_recommendations: list[str]
    technical_warnings: list[str]
    change_summary: str


class PromptRefinementAssistantService:
    _DOMAIN_FIELD_HINTS: dict[str, tuple[str, ...]] = {
        "prazo": ("prazo", "data limite", "vencimento", "deadline"),
        "responsavel": ("responsavel", "responsavel tecnico", "owner", "encarregado"),
        "categoria": ("categoria", "classificacao", "tipo", "assunto"),
        "resumo": ("resumo", "sumario", "sintese"),
        "pensamento": ("pensamento", "raciocinio", "justificativa", "motivo"),
        "necessita_revisao": ("necessita revisao", "revisao manual", "validacao manual", "revisar"),
        "compromisso_analista": ("compromisso analista", "acao do analista", "proxima acao", "follow up"),
    }

    _GENERIC_LOW_CONFIDENCE_PHRASES = {
        "ajusta isso",
        "arruma isso",
        "melhore",
        "melhora",
        "corrige",
        "corrija",
        "faz melhor",
        "ok",
    }

    _ACTION_MESSAGE_BY_STATUS = {
        COMPATIBILITY_READY: "O prompt refinado ja e compativel com os campos atuais de resultado.",
        COMPATIBILITY_SCHEMA_UPDATE: "Para atender ao resultado esperado, e necessario adicionar ou remover campos antes da execucao.",
        COMPATIBILITY_MANUAL_REVIEW: "Foi identificada uma necessidade de revisao manual antes de aplicar alteracoes estruturais.",
    }

    def __init__(
        self,
        *,
        shared_session: Session,
        operational_session: Session | None = None,
        catalog_service: ExternalCatalogService | None = None,
    ) -> None:
        self.catalog = catalog_service or ExternalCatalogService(
            shared_session=shared_session,
            operational_session=operational_session,
        )

    def preview(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
        raw_prompt: str,
        expected_result_description: str | None = None,
    ) -> PromptRefinementPreviewResult:
        automation = self.catalog.get_automation_in_scope(
            token_id=token_id,
            automation_id=automation_id,
        )
        current_prompt = self._resolve_latest_prompt_text(
            token_id=token_id,
            automation_id=automation_id,
        )
        current_output_schema = self._coerce_schema_dict(automation.output_schema)
        current_result_fields = self._extract_result_fields(current_output_schema)

        analysis = self._analyze_prompt_intention(
            raw_prompt=raw_prompt,
            expected_result_description=expected_result_description,
            current_result_fields=current_result_fields,
        )
        fields_to_add, fields_to_remove = self._calculate_diff(
            current_fields=current_result_fields,
            suggested_fields=analysis.suggested_result_fields,
        )
        compatibility_status = self._classify_status(
            low_confidence=analysis.low_confidence,
            fields_to_add=fields_to_add,
            fields_to_remove=fields_to_remove,
        )
        proposed_schema = self._build_proposed_schema(
            current_schema=current_output_schema,
            current_result_fields=current_result_fields,
            suggested_result_fields=analysis.suggested_result_fields,
        )
        can_execute_now = compatibility_status == COMPATIBILITY_READY

        return PromptRefinementPreviewResult(
            automation_id=automation.id,
            prompt_original=current_prompt,
            prompt_received=str(raw_prompt or "").strip(),
            refined_prompt=analysis.refined_prompt,
            current_result_fields=current_result_fields,
            suggested_result_fields=analysis.suggested_result_fields,
            fields_to_add=fields_to_add,
            fields_to_remove=fields_to_remove,
            proposed_output_schema=proposed_schema,
            compatibility_status=compatibility_status,
            can_execute_now=can_execute_now,
            action_required_message=self._ACTION_MESSAGE_BY_STATUS[compatibility_status],
        )

    def advanced_preview(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
        raw_prompt: str,
        expected_result_description: str | None = None,
    ) -> PromptRefinementAdvancedPreviewResult:
        automation = self.catalog.get_automation_in_scope(
            token_id=token_id,
            automation_id=automation_id,
        )
        current_prompt = self._resolve_latest_prompt_text(
            token_id=token_id,
            automation_id=automation_id,
        )
        current_output_schema = self._coerce_schema_dict(automation.output_schema)
        current_result_fields = self._extract_result_fields(current_output_schema)

        analysis = self._analyze_prompt_intention(
            raw_prompt=raw_prompt,
            expected_result_description=expected_result_description,
            current_result_fields=current_result_fields,
        )
        fields_to_add, fields_to_remove = self._calculate_diff(
            current_fields=current_result_fields,
            suggested_fields=analysis.suggested_result_fields,
        )
        proposed_schema = self._build_proposed_schema(
            current_schema=current_output_schema,
            current_result_fields=current_result_fields,
            suggested_result_fields=analysis.suggested_result_fields,
        )
        compatibility_status = self._classify_status(
            low_confidence=analysis.low_confidence,
            fields_to_add=fields_to_add,
            fields_to_remove=fields_to_remove,
        )
        can_execute_now = compatibility_status == COMPATIBILITY_READY

        schema_diff = self._build_schema_diff(
            current_schema=current_output_schema,
            proposed_schema=proposed_schema,
            current_result_fields=current_result_fields,
            suggested_result_fields=analysis.suggested_result_fields,
        )
        placeholder_analysis = self._build_placeholder_analysis(
            corrected_prompt=analysis.refined_prompt,
            current_schema=current_output_schema,
            suggested_result_fields=analysis.suggested_result_fields,
            fields_to_add=fields_to_add,
            fields_to_remove=fields_to_remove,
        )
        mapping_analysis = self._build_mapping_analysis(
            current_schema=current_output_schema,
            proposed_schema=proposed_schema,
        )
        confidence_level = self._derive_confidence_level(
            low_confidence=analysis.low_confidence,
            fields_to_add=fields_to_add,
            fields_to_remove=fields_to_remove,
            placeholder_analysis=placeholder_analysis,
            mapping_analysis=mapping_analysis,
        )
        technical_warnings = self._build_technical_warnings(
            compatibility_status=compatibility_status,
            confidence_level=confidence_level,
            placeholder_analysis=placeholder_analysis,
            mapping_analysis=mapping_analysis,
            schema_diff=schema_diff,
        )
        review_recommendations = self._build_review_recommendations(
            confidence_level=confidence_level,
            fields_to_add=fields_to_add,
            fields_to_remove=fields_to_remove,
            placeholder_analysis=placeholder_analysis,
            mapping_analysis=mapping_analysis,
        )
        safe_apply_options = self._build_safe_apply_options(
            confidence_level=confidence_level,
            compatibility_status=compatibility_status,
        )

        return PromptRefinementAdvancedPreviewResult(
            automation_id=automation.id,
            raw_prompt=str(raw_prompt or "").strip(),
            corrected_prompt=analysis.refined_prompt,
            prompt_original=current_prompt,
            current_prompt_summary=self._summarize_prompt(current_prompt),
            prompt_change_summary=self._build_prompt_change_summary(
                raw_prompt=str(raw_prompt or "").strip(),
                corrected_prompt=analysis.refined_prompt,
            ),
            current_result_fields=current_result_fields,
            suggested_result_fields=analysis.suggested_result_fields,
            fields_to_add=fields_to_add,
            fields_to_remove=fields_to_remove,
            current_output_schema=current_output_schema,
            proposed_output_schema=proposed_schema,
            schema_diff=schema_diff,
            placeholder_analysis=placeholder_analysis,
            mapping_analysis=mapping_analysis,
            confidence_level=confidence_level,
            compatibility_status=compatibility_status,
            can_execute_now=can_execute_now,
            action_required_message=self._ACTION_MESSAGE_BY_STATUS[compatibility_status],
            review_recommendations=review_recommendations,
            technical_warnings=technical_warnings,
            safe_apply_options=safe_apply_options,
        )

    def advanced_apply(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
        corrected_prompt: str | None,
        expected_result_description: str | None,
        apply_prompt_update: bool,
        apply_schema_update: bool,
        reviewed_output_schema: dict[str, Any] | None,
        create_new_prompt_version: bool,
        confirm_apply: bool,
        confirm_manual_review: bool,
        allow_field_removals: bool,
    ) -> PromptRefinementAdvancedApplyResult:
        automation = self.catalog.get_automation_in_scope(
            token_id=token_id,
            automation_id=automation_id,
        )
        current_prompt = self._resolve_latest_prompt_text(
            token_id=token_id,
            automation_id=automation_id,
        )
        current_output_schema = self._coerce_schema_dict(automation.output_schema)
        current_result_fields = self._extract_result_fields(current_output_schema)

        effective_prompt = str(corrected_prompt or "").strip() or str(current_prompt or "").strip()
        analysis = self._analyze_prompt_intention(
            raw_prompt=effective_prompt,
            expected_result_description=expected_result_description,
            current_result_fields=current_result_fields,
        )
        suggested_result_fields = analysis.suggested_result_fields
        fields_to_add, fields_to_remove = self._calculate_diff(
            current_fields=current_result_fields,
            suggested_fields=suggested_result_fields,
        )

        proposed_schema = self._build_proposed_schema(
            current_schema=current_output_schema,
            current_result_fields=current_result_fields,
            suggested_result_fields=suggested_result_fields,
        )
        if reviewed_output_schema is not None:
            proposed_schema = self._merge_reviewed_schema(
                current_schema=current_output_schema,
                reviewed_schema=reviewed_output_schema,
            )

        if apply_schema_update:
            candidate_fields = self._extract_result_fields(proposed_schema)
            _, candidate_removed_fields = self._calculate_diff(
                current_fields=current_result_fields,
                suggested_fields=candidate_fields,
            )
            if candidate_removed_fields and not allow_field_removals:
                raise AppException(
                    "Field removal is blocked by current safety flags.",
                    status_code=422,
                    code="prompt_refinement_field_removal_blocked",
                    details={"fields_to_remove": candidate_removed_fields},
                )

        placeholder_analysis = self._build_placeholder_analysis(
            corrected_prompt=analysis.refined_prompt,
            current_schema=current_output_schema,
            suggested_result_fields=suggested_result_fields,
            fields_to_add=fields_to_add,
            fields_to_remove=fields_to_remove,
        )
        mapping_analysis = self._build_mapping_analysis(
            current_schema=current_output_schema,
            proposed_schema=proposed_schema,
        )
        confidence_level = self._derive_confidence_level(
            low_confidence=analysis.low_confidence,
            fields_to_add=fields_to_add,
            fields_to_remove=fields_to_remove,
            placeholder_analysis=placeholder_analysis,
            mapping_analysis=mapping_analysis,
        )
        compatibility_status = self._classify_status(
            low_confidence=analysis.low_confidence,
            fields_to_add=fields_to_add,
            fields_to_remove=fields_to_remove,
        )

        if confidence_level == CONFIDENCE_LOW and apply_schema_update and not confirm_manual_review:
            raise AppException(
                "Low confidence schema changes require explicit manual review confirmation.",
                status_code=422,
                code="prompt_refinement_manual_review_confirmation_required",
            )

        apply_result = self.apply(
            token_id=token_id,
            automation_id=automation_id,
            corrected_prompt=analysis.refined_prompt if apply_prompt_update else corrected_prompt,
            apply_prompt_update=apply_prompt_update,
            apply_schema_update=apply_schema_update,
            proposed_output_schema=proposed_schema if apply_schema_update else None,
            create_new_prompt_version=create_new_prompt_version,
            confirm_apply=confirm_apply,
            allow_low_confidence_schema_apply=confirm_manual_review,
        )

        applied_output_schema = self._coerce_schema_dict(apply_result.output_schema)
        schema_diff = self._build_schema_diff(
            current_schema=current_output_schema,
            proposed_schema=applied_output_schema if applied_output_schema else proposed_schema,
            current_result_fields=current_result_fields,
            suggested_result_fields=apply_result.current_result_fields,
        )
        final_placeholder_analysis = self._build_placeholder_analysis(
            corrected_prompt=apply_result.applied_prompt_text or analysis.refined_prompt,
            current_schema=applied_output_schema,
            suggested_result_fields=apply_result.suggested_result_fields,
            fields_to_add=apply_result.fields_added,
            fields_to_remove=apply_result.fields_removed,
        )
        final_mapping_analysis = self._build_mapping_analysis(
            current_schema=current_output_schema,
            proposed_schema=applied_output_schema if applied_output_schema else proposed_schema,
        )
        final_confidence_level = self._derive_confidence_level(
            low_confidence=analysis.low_confidence,
            fields_to_add=apply_result.fields_added,
            fields_to_remove=apply_result.fields_removed,
            placeholder_analysis=final_placeholder_analysis,
            mapping_analysis=final_mapping_analysis,
        )
        technical_warnings = self._build_technical_warnings(
            compatibility_status=compatibility_status,
            confidence_level=final_confidence_level,
            placeholder_analysis=final_placeholder_analysis,
            mapping_analysis=final_mapping_analysis,
            schema_diff=schema_diff,
        )
        review_recommendations = self._build_review_recommendations(
            confidence_level=final_confidence_level,
            fields_to_add=apply_result.fields_added,
            fields_to_remove=apply_result.fields_removed,
            placeholder_analysis=final_placeholder_analysis,
            mapping_analysis=final_mapping_analysis,
        )

        return PromptRefinementAdvancedApplyResult(
            automation_id=apply_result.automation_id,
            automation_name=apply_result.automation_name,
            automation_is_active=apply_result.automation_is_active,
            output_schema=apply_result.output_schema,
            prompt_update_applied=apply_result.prompt_update_applied,
            schema_update_applied=apply_result.schema_update_applied,
            updated_prompt_id=apply_result.updated_prompt_id,
            updated_prompt_version=apply_result.updated_prompt_version,
            applied_prompt_text=apply_result.applied_prompt_text,
            previous_result_fields=apply_result.previous_result_fields,
            current_result_fields=apply_result.current_result_fields,
            suggested_result_fields=apply_result.suggested_result_fields,
            fields_added=apply_result.fields_added,
            fields_removed=apply_result.fields_removed,
            current_output_schema=current_output_schema,
            applied_output_schema=applied_output_schema,
            schema_diff=schema_diff,
            placeholder_analysis=final_placeholder_analysis,
            mapping_analysis=final_mapping_analysis,
            confidence_level=final_confidence_level,
            compatibility_status=compatibility_status,
            can_execute_now=apply_result.can_execute_now,
            action_required_message=apply_result.action_required_message,
            review_recommendations=review_recommendations,
            technical_warnings=technical_warnings,
            change_summary=apply_result.change_summary,
        )

    def apply(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
        corrected_prompt: str | None,
        apply_prompt_update: bool,
        apply_schema_update: bool,
        proposed_output_schema: dict[str, Any] | None,
        create_new_prompt_version: bool = False,
        confirm_apply: bool,
        allow_low_confidence_schema_apply: bool = False,
    ) -> PromptRefinementApplyResult:
        if not confirm_apply:
            raise AppException(
                "Apply requires explicit confirmation.",
                status_code=422,
                code="prompt_refinement_apply_confirmation_required",
            )
        if not apply_prompt_update and not apply_schema_update:
            raise AppException(
                "At least one apply flag must be true.",
                status_code=422,
                code="prompt_refinement_apply_empty",
            )

        automation = self.catalog.get_automation_in_scope(
            token_id=token_id,
            automation_id=automation_id,
        )
        previous_output_schema = self._coerce_schema_dict(automation.output_schema)
        previous_result_fields = self._extract_result_fields(previous_output_schema)

        sanitized_prompt = str(corrected_prompt or "").strip()
        if apply_prompt_update and not sanitized_prompt:
            raise AppException(
                "corrected_prompt is required when apply_prompt_update is true.",
                status_code=422,
                code="validation_error",
                details={"field": "corrected_prompt"},
            )

        prompt_update_applied = False
        updated_prompt_id: uuid.UUID | None = None
        updated_prompt_version: int | None = None
        applied_prompt_text: str | None = None

        if apply_prompt_update:
            if create_new_prompt_version:
                updated_prompt = self.catalog.create_prompt(
                    token_id=token_id,
                    automation_id=automation_id,
                    prompt_text=sanitized_prompt,
                )
            else:
                target_prompt = self._resolve_latest_prompt_record(
                    token_id=token_id,
                    automation_id=automation_id,
                )
                if target_prompt is None:
                    updated_prompt = self.catalog.create_prompt(
                        token_id=token_id,
                        automation_id=automation_id,
                        prompt_text=sanitized_prompt,
                    )
                else:
                    updated_prompt = self.catalog.update_prompt(
                        token_id=token_id,
                        prompt_id=target_prompt.id,
                        prompt_text=sanitized_prompt,
                    )
            prompt_update_applied = True
            updated_prompt_id = updated_prompt.id
            updated_prompt_version = updated_prompt.version
            applied_prompt_text = updated_prompt.prompt_text

        schema_update_applied = False
        updated_automation = automation
        if apply_schema_update:
            if proposed_output_schema is None:
                raise AppException(
                    "proposed_output_schema is required when apply_schema_update is true.",
                    status_code=422,
                    code="validation_error",
                    details={"field": "proposed_output_schema"},
                )
            confidence_prompt = sanitized_prompt or self._resolve_latest_prompt_text(
                token_id=token_id,
                automation_id=automation_id,
            ) or ""
            confidence_analysis = self._analyze_prompt_intention(
                raw_prompt=confidence_prompt,
                expected_result_description=None,
                current_result_fields=previous_result_fields,
            )
            if confidence_analysis.low_confidence and not allow_low_confidence_schema_apply:
                raise AppException(
                    "Manual review is required before applying structural schema changes.",
                    status_code=422,
                    code="prompt_refinement_manual_review_required",
                )
            normalized_schema = self._coerce_schema_dict(proposed_output_schema)
            self._validate_conservative_schema_update(
                current_schema=previous_output_schema,
                proposed_schema=normalized_schema,
            )
            updated_automation = self.catalog.update_automation(
                token_id=token_id,
                automation_id=automation_id,
                changes={"output_schema": normalized_schema},
            )
            schema_update_applied = True
        elif prompt_update_applied:
            updated_automation = self.catalog.get_automation_in_scope(
                token_id=token_id,
                automation_id=automation_id,
            )

        current_output_schema = self._coerce_schema_dict(updated_automation.output_schema)
        current_result_fields = self._extract_result_fields(current_output_schema)

        effective_prompt = sanitized_prompt or self._resolve_latest_prompt_text(
            token_id=token_id,
            automation_id=automation_id,
        )
        analysis = self._analyze_prompt_intention(
            raw_prompt=effective_prompt or "",
            expected_result_description=None,
            current_result_fields=current_result_fields,
        )
        suggested_result_fields = analysis.suggested_result_fields
        fields_to_add_vs_current, fields_to_remove_vs_current = self._calculate_diff(
            current_fields=current_result_fields,
            suggested_fields=suggested_result_fields,
        )
        compatibility_status = self._classify_status(
            low_confidence=analysis.low_confidence,
            fields_to_add=fields_to_add_vs_current,
            fields_to_remove=fields_to_remove_vs_current,
        )
        can_execute_now = compatibility_status == COMPATIBILITY_READY

        fields_added, fields_removed = self._calculate_diff(
            current_fields=previous_result_fields,
            suggested_fields=current_result_fields,
        )
        summary = self._build_apply_change_summary(
            prompt_update_applied=prompt_update_applied,
            schema_update_applied=schema_update_applied,
            fields_added=fields_added,
            fields_removed=fields_removed,
        )

        return PromptRefinementApplyResult(
            automation_id=updated_automation.id,
            automation_name=updated_automation.name,
            automation_is_active=bool(updated_automation.is_active),
            output_schema=(deepcopy(updated_automation.output_schema) if isinstance(updated_automation.output_schema, dict) else None),
            prompt_update_applied=prompt_update_applied,
            schema_update_applied=schema_update_applied,
            updated_prompt_id=updated_prompt_id,
            updated_prompt_version=updated_prompt_version,
            applied_prompt_text=applied_prompt_text,
            previous_result_fields=previous_result_fields,
            current_result_fields=current_result_fields,
            suggested_result_fields=suggested_result_fields,
            fields_added=fields_added,
            fields_removed=fields_removed,
            can_execute_now=can_execute_now,
            action_required_message=self._ACTION_MESSAGE_BY_STATUS[compatibility_status],
            change_summary=summary,
        )

    def _resolve_latest_prompt_record(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
    ):  # type: ignore[no-untyped-def]
        active_prompts = self.catalog.list_prompts(
            token_id=token_id,
            automation_id=automation_id,
            is_active=True,
            limit=1,
            offset=0,
        )
        if active_prompts:
            return active_prompts[0]
        prompts = self.catalog.list_prompts(
            token_id=token_id,
            automation_id=automation_id,
            is_active=None,
            limit=1,
            offset=0,
        )
        return prompts[0] if prompts else None

    def _resolve_latest_prompt_text(
        self,
        *,
        token_id: uuid.UUID,
        automation_id: uuid.UUID,
    ) -> str | None:
        latest = self._resolve_latest_prompt_record(
            token_id=token_id,
            automation_id=automation_id,
        )
        if latest is None:
            return None
        value = str(latest.prompt_text or "").strip()
        return value or None

    @dataclass(slots=True)
    class _IntentionAnalysis:
        refined_prompt: str
        suggested_result_fields: list[str]
        low_confidence: bool

    def _analyze_prompt_intention(
        self,
        *,
        raw_prompt: str,
        expected_result_description: str | None,
        current_result_fields: list[str],
    ) -> _IntentionAnalysis:
        normalized_prompt = str(raw_prompt or "").strip()
        normalized_expected = str(expected_result_description or "").strip()
        combined_for_matching = self._normalize_match_text(
            " ".join(part for part in (normalized_prompt, normalized_expected) if part)
        )

        style = self._detect_field_style(current_result_fields)
        normalized_current_map = {
            self._normalize_field_name(field): field
            for field in current_result_fields
            if self._normalize_field_name(field)
        }

        matched_fields: list[str] = []
        evidence_score = 0

        for canonical_name, keywords in self._DOMAIN_FIELD_HINTS.items():
            if any(self._normalize_match_text(keyword) in combined_for_matching for keyword in keywords):
                resolved = normalized_current_map.get(canonical_name) or self._render_field_name(
                    canonical_name,
                    style=style,
                )
                matched_fields.append(resolved)
                evidence_score += 2

        for placeholder in re.findall(r"\{\{\s*([^{}]+)\s*\}\}", normalized_prompt):
            normalized_placeholder = self._normalize_field_name(placeholder)
            if not normalized_placeholder:
                continue
            resolved = normalized_current_map.get(normalized_placeholder) or self._render_field_name(
                normalized_placeholder,
                style=style,
            )
            matched_fields.append(resolved)
            evidence_score += 1

        for field in current_result_fields:
            normalized_field = self._normalize_field_name(field)
            if not normalized_field:
                continue
            field_text = normalized_field.replace("_", " ")
            if field_text and field_text in combined_for_matching:
                matched_fields.append(field)
                evidence_score += 1

        if normalized_expected:
            evidence_score += 1
        if len(normalized_prompt) >= 20:
            evidence_score += 1

        suggested_fields = self._unique_preserving_order(matched_fields)
        if not suggested_fields:
            # Conservador: sem sinais claros de mudanca estrutural, manter campos atuais.
            suggested_fields = list(current_result_fields)

        low_confidence = self._is_low_confidence(
            normalized_prompt=normalized_prompt,
            normalized_expected=normalized_expected,
            evidence_score=evidence_score,
            has_detected_fields=bool(suggested_fields),
            current_result_fields=current_result_fields,
        )

        refined_prompt = self._build_refined_prompt(
            raw_prompt=normalized_prompt,
            expected_result_description=normalized_expected,
            suggested_result_fields=suggested_fields,
        )
        return self._IntentionAnalysis(
            refined_prompt=refined_prompt,
            suggested_result_fields=suggested_fields,
            low_confidence=low_confidence,
        )

    def _build_refined_prompt(
        self,
        *,
        raw_prompt: str,
        expected_result_description: str | None,
        suggested_result_fields: list[str],
    ) -> str:
        objective_text = (
            str(expected_result_description or "").strip()
            or "Gerar um resultado claro e consistente para o usuario externo."
        )
        fields_text = ", ".join(suggested_result_fields) if suggested_result_fields else "resultado_textual"
        return (
            "Voce deve processar a solicitacao abaixo e entregar um resultado objetivo.\n"
            f"Objetivo esperado: {objective_text}\n"
            "Instrucao original do usuario:\n"
            f"{raw_prompt}\n"
            "Regras de resposta:\n"
            f"- Preencha os campos de resultado esperados: {fields_text}.\n"
            "- Use linguagem direta e sem ambiguidade.\n"
            "- Quando nao houver informacao suficiente, sinalize claramente no proprio campo."
        )

    def _build_proposed_schema(
        self,
        *,
        current_schema: dict[str, Any] | None,
        current_result_fields: list[str],
        suggested_result_fields: list[str],
    ) -> dict[str, Any]:
        base_schema = deepcopy(current_schema) if isinstance(current_schema, dict) else {}
        next_fields = list(suggested_result_fields or current_result_fields)

        if "output_columns" in base_schema:
            base_schema["output_columns"] = list(next_fields)
        base_schema["columns"] = list(next_fields)

        existing_ai_fields = self._extract_field_list(base_schema.get("ai_output_columns"))
        if existing_ai_fields:
            ai_field_norm = {self._normalize_field_name(field) for field in existing_ai_fields}
            normalized_next = {self._normalize_field_name(field) for field in next_fields}
            ai_output_columns = [
                field
                for field in next_fields
                if self._normalize_field_name(field) in ai_field_norm
                and self._normalize_field_name(field) in normalized_next
            ]
        else:
            operational_fields = {
                self._normalize_field_name(base_schema.get("row_origin_column")),
                self._normalize_field_name(base_schema.get("status_column")),
                self._normalize_field_name(base_schema.get("error_column")),
            }
            ai_output_columns = [
                field
                for field in next_fields
                if self._normalize_field_name(field) not in operational_fields
            ]
        base_schema["ai_output_columns"] = ai_output_columns
        return base_schema

    def _validate_conservative_schema_update(
        self,
        *,
        current_schema: dict[str, Any] | None,
        proposed_schema: dict[str, Any],
    ) -> None:
        allowed_mutable_fields = {"columns", "output_columns", "ai_output_columns"}
        current_schema = current_schema or {}

        for key, proposed_value in proposed_schema.items():
            if key in allowed_mutable_fields:
                continue
            if key not in current_schema:
                raise AppException(
                    "Schema update is limited to result field lists in this version.",
                    status_code=422,
                    code="prompt_refinement_schema_update_not_allowed",
                    details={"field": key, "reason": "new_field_not_allowed"},
                )
            if current_schema.get(key) != proposed_value:
                raise AppException(
                    "Schema update is limited to result field lists in this version.",
                    status_code=422,
                    code="prompt_refinement_schema_update_not_allowed",
                    details={"field": key, "reason": "field_change_not_allowed"},
                )

        for key in current_schema:
            if key in allowed_mutable_fields:
                continue
            if key not in proposed_schema:
                raise AppException(
                    "Schema update must preserve current automation output settings.",
                    status_code=422,
                    code="prompt_refinement_schema_update_not_allowed",
                    details={"field": key, "reason": "field_removal_not_allowed"},
                )

    @staticmethod
    def _coerce_schema_dict(value: object | None) -> dict[str, Any]:
        return deepcopy(value) if isinstance(value, dict) else {}

    def _extract_result_fields(self, output_schema: dict[str, Any] | None) -> list[str]:
        if not isinstance(output_schema, dict):
            return []
        columns = self._extract_field_list(output_schema.get("columns"))
        if not columns:
            columns = self._extract_field_list(output_schema.get("output_columns"))
        if not columns:
            columns = self._extract_field_list(output_schema.get("ai_output_columns"))
        return columns

    @staticmethod
    def _extract_field_list(raw_value: object | None) -> list[str]:
        if raw_value is None:
            return []
        values: list[str] = []
        if isinstance(raw_value, str):
            values = [item.strip() for item in raw_value.split(",")]
        elif isinstance(raw_value, (list, tuple, set)):
            values = [str(item or "").strip() for item in raw_value]
        else:
            return []
        return [item for item in PromptRefinementAssistantService._unique_preserving_order(values) if item]

    @staticmethod
    def _calculate_diff(
        *,
        current_fields: list[str],
        suggested_fields: list[str],
    ) -> tuple[list[str], list[str]]:
        current_map = {
            PromptRefinementAssistantService._normalize_field_name(field): field
            for field in current_fields
            if PromptRefinementAssistantService._normalize_field_name(field)
        }
        suggested_map = {
            PromptRefinementAssistantService._normalize_field_name(field): field
            for field in suggested_fields
            if PromptRefinementAssistantService._normalize_field_name(field)
        }
        fields_to_add = [
            suggested_map[key]
            for key in suggested_map
            if key not in current_map
        ]
        fields_to_remove = [
            current_map[key]
            for key in current_map
            if key not in suggested_map
        ]
        return fields_to_add, fields_to_remove

    @staticmethod
    def _classify_status(
        *,
        low_confidence: bool,
        fields_to_add: list[str],
        fields_to_remove: list[str],
    ) -> str:
        if low_confidence:
            return COMPATIBILITY_MANUAL_REVIEW
        if fields_to_add or fields_to_remove:
            return COMPATIBILITY_SCHEMA_UPDATE
        return COMPATIBILITY_READY

    @classmethod
    def _is_low_confidence(
        cls,
        *,
        normalized_prompt: str,
        normalized_expected: str,
        evidence_score: int,
        has_detected_fields: bool,
        current_result_fields: list[str],
    ) -> bool:
        normalized_phrase = cls._normalize_match_text(normalized_prompt)
        word_count = len([item for item in normalized_phrase.split(" ") if item])
        if normalized_phrase in cls._GENERIC_LOW_CONFIDENCE_PHRASES:
            return True
        if word_count <= 2 and not normalized_expected:
            return True
        if evidence_score < 2 and not normalized_expected:
            return True
        if not has_detected_fields and not current_result_fields:
            return True
        return False

    @staticmethod
    def _build_apply_change_summary(
        *,
        prompt_update_applied: bool,
        schema_update_applied: bool,
        fields_added: list[str],
        fields_removed: list[str],
    ) -> str:
        parts: list[str] = []
        if prompt_update_applied:
            parts.append("Prompt refinado aplicado.")
        if schema_update_applied:
            parts.append("Campos de resultado da automacao atualizados.")
        if fields_added:
            parts.append(f"Campos adicionados: {', '.join(fields_added)}.")
        if fields_removed:
            parts.append(f"Campos removidos: {', '.join(fields_removed)}.")
        if not parts:
            return "Nenhuma alteracao foi aplicada."
        return " ".join(parts)

    def _build_schema_diff(
        self,
        *,
        current_schema: dict[str, Any],
        proposed_schema: dict[str, Any],
        current_result_fields: list[str],
        suggested_result_fields: list[str],
    ) -> dict[str, Any]:
        kept_fields = [
            field
            for field in current_result_fields
            if self._normalize_field_name(field) in {self._normalize_field_name(item) for item in suggested_result_fields}
        ]
        added_fields, removed_fields = self._calculate_diff(
            current_fields=current_result_fields,
            suggested_fields=suggested_result_fields,
        )

        current_ai_fields = self._extract_field_list(current_schema.get("ai_output_columns"))
        suggested_ai_fields = self._extract_field_list(proposed_schema.get("ai_output_columns"))
        ai_added, ai_removed = self._calculate_diff(
            current_fields=current_ai_fields,
            suggested_fields=suggested_ai_fields,
        )

        relevant_changes: list[str] = []
        if added_fields:
            relevant_changes.append(f"Novos campos de resultado detectados: {', '.join(added_fields)}.")
        if removed_fields:
            relevant_changes.append(f"Campos de resultado removidos na proposta: {', '.join(removed_fields)}.")
        if ai_added or ai_removed:
            relevant_changes.append("Lista de ai_output_columns sofreu alteracao.")
        if not relevant_changes:
            relevant_changes.append("Nao houve alteracoes estruturais nos campos de resultado.")

        observations: list[str] = []
        if not current_result_fields:
            observations.append("Schema atual nao possui lista explicita de campos de resultado.")
        if "output_columns" in current_schema and "output_columns" not in proposed_schema:
            observations.append("output_columns do schema atual foi preservado por fallback.")
        if removed_fields:
            observations.append("Remocoes de campos podem afetar integracoes que dependem do layout atual.")

        return {
            "kept_fields": kept_fields,
            "added_fields": added_fields,
            "removed_fields": removed_fields,
            "ai_output_columns_current": current_ai_fields,
            "ai_output_columns_suggested": suggested_ai_fields,
            "ai_output_columns_added": ai_added,
            "ai_output_columns_removed": ai_removed,
            "relevant_changes": relevant_changes,
            "observations": observations,
        }

    def _build_placeholder_analysis(
        self,
        *,
        corrected_prompt: str,
        current_schema: dict[str, Any],
        suggested_result_fields: list[str],
        fields_to_add: list[str],
        fields_to_remove: list[str],
    ) -> dict[str, Any]:
        detected = self._detect_placeholders(corrected_prompt)
        current_schema_fields = self._extract_result_fields(current_schema)
        valid_schema_tokens = self._build_schema_placeholder_tokens(
            schema=current_schema,
            result_fields=current_schema_fields,
        )
        suggested_placeholders = [
            self._render_field_name(self._normalize_field_name(field), style="snake").upper()
            for field in suggested_result_fields
        ]
        normalized_detected = {self._normalize_field_name(token): token for token in detected}
        normalized_valid = {self._normalize_field_name(token): token for token in valid_schema_tokens}
        normalized_suggested = {self._normalize_field_name(token): token for token in suggested_placeholders}

        recommended_missing = [
            normalized_suggested[key]
            for key in normalized_suggested
            if key not in normalized_detected
        ]
        invalid_unresolved = [
            normalized_detected[key]
            for key in normalized_detected
            if key not in normalized_valid
        ]

        impact = "Placeholders estao alinhados com os campos sugeridos."
        if invalid_unresolved:
            impact = "Existem placeholders nao resolvidos pela proposta atual."
        elif recommended_missing:
            impact = "Ha placeholders recomendados ausentes no prompt refinado."
        elif fields_to_add or fields_to_remove:
            impact = "Mudancas de campos exigem revisar placeholders para manter compatibilidade."

        return {
            "detected_in_corrected_prompt": detected,
            "valid_schema_placeholders": valid_schema_tokens,
            "suggested_placeholders": suggested_placeholders,
            "recommended_missing_placeholders": recommended_missing,
            "invalid_or_unresolved_placeholders": invalid_unresolved,
            "impact_summary": impact,
        }

    def _build_mapping_analysis(
        self,
        *,
        current_schema: dict[str, Any],
        proposed_schema: dict[str, Any],
    ) -> dict[str, Any]:
        input_mappings = current_schema.get("input_column_mappings")
        prompt_field_columns = current_schema.get("prompt_field_columns")
        proposed_fields = set(self._extract_result_fields(proposed_schema))

        preserved: list[str] = []
        affected: list[str] = []
        ambiguities: list[str] = []

        if isinstance(prompt_field_columns, dict):
            for field_name, column_name in prompt_field_columns.items():
                key = str(field_name or "").strip()
                target = str(column_name or "").strip()
                if not key:
                    continue
                if not target:
                    ambiguities.append(key)
                    continue
                if proposed_fields and target not in proposed_fields:
                    affected.append(key)
                else:
                    preserved.append(key)

        if isinstance(input_mappings, dict):
            for source_name, target_spec in input_mappings.items():
                key = str(source_name or "").strip()
                if not key:
                    continue
                targets = self._extract_mapping_targets(target_spec)
                unique_targets = {
                    str(target or "").strip()
                    for target in targets
                    if str(target or "").strip()
                }
                if len(unique_targets) > 1:
                    ambiguities.append(key)
                if not unique_targets:
                    ambiguities.append(key)
                    continue
                if proposed_fields and any(target not in proposed_fields for target in unique_targets):
                    affected.append(key)
                else:
                    preserved.append(key)

        preserved = self._unique_preserving_order(preserved)
        affected = self._unique_preserving_order(affected)
        ambiguities = self._unique_preserving_order(ambiguities)
        needs_review = bool(affected or ambiguities)
        impact = "Mappings preservados sem impacto relevante."
        if ambiguities:
            impact = "Foram detectadas ambiguidades de mapping que exigem revisao."
        elif affected:
            impact = "Parte dos mappings pode ser afetada pelas mudancas de campos."

        return {
            "mappings_preserved": preserved,
            "mappings_potentially_affected": affected,
            "mapping_ambiguities": ambiguities,
            "needs_review": needs_review,
            "impact_summary": impact,
        }

    @staticmethod
    def _extract_mapping_targets(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple, set)):
            targets: list[str] = []
            for item in value:
                targets.extend(PromptRefinementAssistantService._extract_mapping_targets(item))
            return targets
        if isinstance(value, dict):
            targets: list[str] = []
            for key, item in value.items():
                normalized_key = str(key or "").strip().casefold()
                if normalized_key in {"target", "column", "to", "destination"} and item is not None:
                    targets.append(str(item))
                else:
                    targets.extend(PromptRefinementAssistantService._extract_mapping_targets(item))
            return targets
        return [str(value)]

    def _derive_confidence_level(
        self,
        *,
        low_confidence: bool,
        fields_to_add: list[str],
        fields_to_remove: list[str],
        placeholder_analysis: dict[str, Any],
        mapping_analysis: dict[str, Any],
    ) -> str:
        if low_confidence:
            return CONFIDENCE_LOW
        risk_score = 0
        if fields_to_add or fields_to_remove:
            risk_score += 1
        if placeholder_analysis.get("invalid_or_unresolved_placeholders"):
            risk_score += 1
        if mapping_analysis.get("needs_review"):
            risk_score += 1
        if risk_score <= 0:
            return CONFIDENCE_HIGH
        return CONFIDENCE_MEDIUM

    def _build_technical_warnings(
        self,
        *,
        compatibility_status: str,
        confidence_level: str,
        placeholder_analysis: dict[str, Any],
        mapping_analysis: dict[str, Any],
        schema_diff: dict[str, Any],
    ) -> list[str]:
        warnings: list[str] = []
        if compatibility_status == COMPATIBILITY_SCHEMA_UPDATE:
            warnings.append("A execucao imediata pode falhar sem aplicar atualizacao de campos de resultado.")
        if compatibility_status == COMPATIBILITY_MANUAL_REVIEW:
            warnings.append("Caso classificado para revisao manual antes de alteracoes estruturais.")
        if confidence_level == CONFIDENCE_LOW:
            warnings.append("Nivel de confianca baixo para mudancas estruturais automaticas.")
        invalid_tokens = placeholder_analysis.get("invalid_or_unresolved_placeholders") or []
        if invalid_tokens:
            warnings.append(f"Placeholders nao resolvidos: {', '.join(invalid_tokens)}.")
        if mapping_analysis.get("needs_review"):
            warnings.append("Mappings atuais possuem impacto potencial e devem ser revisados.")
        removed_fields = schema_diff.get("removed_fields") or []
        if removed_fields:
            warnings.append(f"Remocao de campos detectada: {', '.join(removed_fields)}.")
        return self._unique_preserving_order(warnings)

    def _build_review_recommendations(
        self,
        *,
        confidence_level: str,
        fields_to_add: list[str],
        fields_to_remove: list[str],
        placeholder_analysis: dict[str, Any],
        mapping_analysis: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []
        if fields_to_add:
            recommendations.append("Validar se os novos campos de resultado sao obrigatorios para o fluxo operacional.")
        if fields_to_remove:
            recommendations.append("Confirmar com times consumidores antes de remover campos existentes.")
        if placeholder_analysis.get("recommended_missing_placeholders"):
            recommendations.append("Revisar placeholders recomendados para melhorar rastreabilidade no prompt.")
        if mapping_analysis.get("needs_review"):
            recommendations.append("Executar revisao tecnica dos mappings antes do apply estrutural.")
        if confidence_level == CONFIDENCE_LOW:
            recommendations.append("Aplicar alteracoes somente com confirmacao manual explicita.")
        if not recommendations:
            recommendations.append("Analise tecnica sem bloqueios relevantes; apply pode seguir com confirmacao.")
        return self._unique_preserving_order(recommendations)

    @staticmethod
    def _build_safe_apply_options(
        *,
        confidence_level: str,
        compatibility_status: str,
    ) -> dict[str, bool]:
        _ = compatibility_status
        requires_manual = confidence_level == CONFIDENCE_LOW
        return {
            "can_apply_prompt_only": True,
            "can_apply_schema_only": True,
            "can_apply_prompt_and_schema": True,
            "requires_manual_review_confirmation": requires_manual,
        }

    @staticmethod
    def _summarize_prompt(prompt_text: str | None, *, limit: int = 200) -> str | None:
        normalized = str(prompt_text or "").strip()
        if not normalized:
            return None
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: limit - 3]}..."

    @staticmethod
    def _build_prompt_change_summary(
        *,
        raw_prompt: str,
        corrected_prompt: str,
    ) -> str:
        raw = str(raw_prompt or "").strip()
        corrected = str(corrected_prompt or "").strip()
        if not raw and not corrected:
            return "Nao houve conteudo de prompt para comparar."
        if raw == corrected:
            return "Prompt refinado manteve o mesmo conteudo da entrada."
        delta = len(corrected) - len(raw)
        if delta == 0:
            return "Prompt refinado alterado com tamanho equivalente ao original."
        if delta > 0:
            return f"Prompt refinado expandiu instrucoes em {delta} caracteres."
        return f"Prompt refinado simplificou instrucoes em {abs(delta)} caracteres."

    @classmethod
    def _detect_placeholders(cls, prompt_text: str | None) -> list[str]:
        tokens = re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", str(prompt_text or ""))
        cleaned = [str(token).strip() for token in tokens if str(token).strip()]
        return cls._unique_preserving_order(cleaned)

    def _build_schema_placeholder_tokens(
        self,
        *,
        schema: dict[str, Any],
        result_fields: list[str],
    ) -> list[str]:
        tokens: list[str] = []
        raw_placeholders = schema.get("prompt_placeholders")
        if isinstance(raw_placeholders, dict):
            for value in raw_placeholders.values():
                normalized = str(value or "").strip()
                if normalized:
                    tokens.append(normalized)
        for field in result_fields:
            normalized = self._normalize_field_name(field)
            if not normalized:
                continue
            tokens.append(normalized)
            tokens.append(normalized.upper())
        return self._unique_preserving_order(tokens)

    def _merge_reviewed_schema(
        self,
        *,
        current_schema: dict[str, Any],
        reviewed_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(reviewed_schema, dict):
            raise AppException(
                "reviewed_output_schema must be a JSON object.",
                status_code=422,
                code="execution_output_schema_invalid",
            )
        allowed_keys = {"columns", "output_columns", "ai_output_columns"}
        disallowed_keys = sorted(key for key in reviewed_schema if key not in allowed_keys)
        if disallowed_keys:
            raise AppException(
                "Reviewed schema exceeded the allowed safe review scope.",
                status_code=422,
                code="prompt_refinement_reviewed_schema_out_of_scope",
                details={"disallowed_keys": disallowed_keys},
            )

        merged = deepcopy(current_schema)
        for key in allowed_keys:
            if key in reviewed_schema:
                merged[key] = self._extract_field_list(reviewed_schema.get(key))

        if not self._extract_field_list(merged.get("columns")):
            fallback_columns = self._extract_field_list(merged.get("output_columns")) or self._extract_field_list(
                merged.get("ai_output_columns")
            )
            if fallback_columns:
                merged["columns"] = fallback_columns
        return merged

    @staticmethod
    def _normalize_match_text(value: object | None) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @staticmethod
    def _normalize_field_name(value: object | None) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
        return normalized

    @classmethod
    def _render_field_name(cls, canonical_field: str, *, style: str) -> str:
        normalized = cls._normalize_field_name(canonical_field)
        if style == "camel":
            chunks = [chunk for chunk in normalized.split("_") if chunk]
            if not chunks:
                return normalized
            return chunks[0] + "".join(chunk.capitalize() for chunk in chunks[1:])
        return normalized

    @staticmethod
    def _detect_field_style(fields: list[str]) -> str:
        snake_score = sum(1 for field in fields if "_" in str(field))
        camel_score = sum(
            1
            for field in fields
            if "_" not in str(field) and any(char.isupper() for char in str(field)[1:])
        )
        if camel_score > snake_score and camel_score > 0:
            return "camel"
        return "snake"

    @staticmethod
    def _unique_preserving_order(values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            normalized = str(value or "").strip()
            if not normalized:
                continue
            marker = normalized.casefold()
            if marker in seen:
                continue
            seen.add(marker)
            ordered.append(normalized)
        return ordered
