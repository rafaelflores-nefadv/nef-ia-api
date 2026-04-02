from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


PromptRefinementCompatibilityStatus = Literal[
    "ready_without_schema_changes",
    "ready_with_schema_update_required",
    "needs_manual_review",
]
PromptRefinementConfidenceLevel = Literal["high", "medium", "low"]


class PromptRefinementPreviewRequest(_StrictRequestModel):
    automation_id: UUID
    raw_prompt: str = Field(min_length=1)
    expected_result_description: str | None = Field(default=None, min_length=1, max_length=2000)


class PromptRefinementPreviewResponse(BaseModel):
    automation_id: UUID
    prompt_original: str | None = None
    prompt_received: str
    refined_prompt: str
    current_result_fields: list[str]
    suggested_result_fields: list[str]
    fields_to_add: list[str]
    fields_to_remove: list[str]
    proposed_output_schema: dict[str, Any] | None = None
    compatibility_status: PromptRefinementCompatibilityStatus
    can_execute_now: bool
    action_required_message: str


class PromptRefinementApplyRequest(_StrictRequestModel):
    automation_id: UUID
    corrected_prompt: str | None = Field(default=None, min_length=1)
    apply_prompt_update: bool = True
    apply_schema_update: bool = False
    proposed_output_schema: dict[str, Any] | None = None
    create_new_prompt_version: bool = False
    confirm_apply: Literal[True]

    @model_validator(mode="after")
    def _validate_apply_flags(self) -> "PromptRefinementApplyRequest":
        if not self.apply_prompt_update and not self.apply_schema_update:
            raise ValueError("At least one apply flag must be true.")
        if self.apply_prompt_update and not str(self.corrected_prompt or "").strip():
            raise ValueError("corrected_prompt is required when apply_prompt_update is true.")
        if self.apply_schema_update and self.proposed_output_schema is None:
            raise ValueError("proposed_output_schema is required when apply_schema_update is true.")
        return self


class PromptRefinementApplyAutomationResponse(BaseModel):
    id: UUID
    name: str
    is_active: bool
    output_schema: dict[str, Any] | None = None


class PromptRefinementApplyResponse(BaseModel):
    automation: PromptRefinementApplyAutomationResponse
    prompt_update_applied: bool
    schema_update_applied: bool
    updated_prompt_id: UUID | None = None
    updated_prompt_version: int | None = None
    applied_prompt_text: str | None = None
    previous_result_fields: list[str]
    current_result_fields: list[str]
    suggested_result_fields: list[str]
    fields_added: list[str]
    fields_removed: list[str]
    can_execute_now: bool
    action_required_message: str
    change_summary: str


class PromptRefinementSchemaDiff(BaseModel):
    kept_fields: list[str]
    added_fields: list[str]
    removed_fields: list[str]
    ai_output_columns_current: list[str]
    ai_output_columns_suggested: list[str]
    ai_output_columns_added: list[str]
    ai_output_columns_removed: list[str]
    relevant_changes: list[str]
    observations: list[str]


class PromptRefinementPlaceholderAnalysis(BaseModel):
    detected_in_corrected_prompt: list[str]
    valid_schema_placeholders: list[str]
    suggested_placeholders: list[str]
    recommended_missing_placeholders: list[str]
    invalid_or_unresolved_placeholders: list[str]
    impact_summary: str


class PromptRefinementMappingAnalysis(BaseModel):
    mappings_preserved: list[str]
    mappings_potentially_affected: list[str]
    mapping_ambiguities: list[str]
    needs_review: bool
    impact_summary: str


class PromptRefinementSafeApplyOptions(BaseModel):
    can_apply_prompt_only: bool
    can_apply_schema_only: bool
    can_apply_prompt_and_schema: bool
    requires_manual_review_confirmation: bool


class PromptRefinementAdvancedPreviewRequest(_StrictRequestModel):
    automation_id: UUID
    raw_prompt: str = Field(min_length=1)
    expected_result_description: str | None = Field(default=None, min_length=1, max_length=2000)


class PromptRefinementAdvancedPreviewResponse(BaseModel):
    automation_id: UUID
    raw_prompt: str
    corrected_prompt: str
    prompt_original: str | None = None
    current_prompt_summary: str | None = None
    prompt_change_summary: str
    current_result_fields: list[str]
    suggested_result_fields: list[str]
    fields_to_add: list[str]
    fields_to_remove: list[str]
    current_output_schema: dict[str, Any] | None = None
    proposed_output_schema: dict[str, Any] | None = None
    schema_diff: PromptRefinementSchemaDiff
    placeholder_analysis: PromptRefinementPlaceholderAnalysis
    mapping_analysis: PromptRefinementMappingAnalysis
    confidence_level: PromptRefinementConfidenceLevel
    compatibility_status: PromptRefinementCompatibilityStatus
    can_execute_now: bool
    action_required_message: str
    review_recommendations: list[str]
    technical_warnings: list[str]
    safe_apply_options: PromptRefinementSafeApplyOptions


class PromptRefinementAdvancedApplyRequest(_StrictRequestModel):
    automation_id: UUID
    corrected_prompt: str | None = Field(default=None, min_length=1)
    expected_result_description: str | None = Field(default=None, min_length=1, max_length=2000)
    apply_prompt_update: bool = True
    apply_schema_update: bool = False
    reviewed_output_schema: dict[str, Any] | None = None
    create_new_prompt_version: bool = False
    confirm_apply: Literal[True]
    confirm_manual_review: bool = False
    allow_field_removals: bool = True

    @model_validator(mode="after")
    def _validate_apply_flags(self) -> "PromptRefinementAdvancedApplyRequest":
        if not self.apply_prompt_update and not self.apply_schema_update:
            raise ValueError("At least one apply flag must be true.")
        if self.apply_prompt_update and not str(self.corrected_prompt or "").strip():
            raise ValueError("corrected_prompt is required when apply_prompt_update is true.")
        if self.apply_schema_update and self.reviewed_output_schema is None:
            if not str(self.corrected_prompt or "").strip() and not str(self.expected_result_description or "").strip():
                raise ValueError(
                    "Provide reviewed_output_schema or corrected_prompt/expected_result_description when apply_schema_update is true."
                )
        return self


class PromptRefinementAdvancedApplyResponse(BaseModel):
    automation: PromptRefinementApplyAutomationResponse
    prompt_update_applied: bool
    schema_update_applied: bool
    updated_prompt_id: UUID | None = None
    updated_prompt_version: int | None = None
    applied_prompt_text: str | None = None
    previous_result_fields: list[str]
    current_result_fields: list[str]
    suggested_result_fields: list[str]
    fields_added: list[str]
    fields_removed: list[str]
    current_output_schema: dict[str, Any] | None = None
    applied_output_schema: dict[str, Any] | None = None
    schema_diff: PromptRefinementSchemaDiff
    placeholder_analysis: PromptRefinementPlaceholderAnalysis
    mapping_analysis: PromptRefinementMappingAnalysis
    confidence_level: PromptRefinementConfidenceLevel
    compatibility_status: PromptRefinementCompatibilityStatus
    can_execute_now: bool
    action_required_message: str
    review_recommendations: list[str]
    technical_warnings: list[str]
    change_summary: str
