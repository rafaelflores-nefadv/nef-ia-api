from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.security import TokenScope, get_current_token_scope
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.schemas.external_prompt_refinement_assistant import (
    PromptRefinementAdvancedApplyRequest,
    PromptRefinementAdvancedApplyResponse,
    PromptRefinementAdvancedPreviewRequest,
    PromptRefinementAdvancedPreviewResponse,
    PromptRefinementApplyAutomationResponse,
    PromptRefinementApplyRequest,
    PromptRefinementApplyResponse,
    PromptRefinementMappingAnalysis,
    PromptRefinementPlaceholderAnalysis,
    PromptRefinementPreviewRequest,
    PromptRefinementPreviewResponse,
    PromptRefinementSafeApplyOptions,
    PromptRefinementSchemaDiff,
)
from app.services.prompt_refinement_assistant_service import PromptRefinementAssistantService

router = APIRouter(prefix="/api/v1/external/assistants", tags=["external-assistants"])


@router.post("/prompt-refinement/preview", response_model=PromptRefinementPreviewResponse)
def preview_prompt_refinement(
    payload: PromptRefinementPreviewRequest,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptRefinementPreviewResponse:
    result = PromptRefinementAssistantService(
        shared_session=shared_session,
        operational_session=operational_session,
    ).preview(
        token_id=token_scope.token_id,
        automation_id=payload.automation_id,
        raw_prompt=payload.raw_prompt,
        expected_result_description=payload.expected_result_description,
    )
    return PromptRefinementPreviewResponse(
        automation_id=result.automation_id,
        prompt_original=result.prompt_original,
        prompt_received=result.prompt_received,
        refined_prompt=result.refined_prompt,
        current_result_fields=result.current_result_fields,
        suggested_result_fields=result.suggested_result_fields,
        fields_to_add=result.fields_to_add,
        fields_to_remove=result.fields_to_remove,
        proposed_output_schema=result.proposed_output_schema,
        compatibility_status=result.compatibility_status,  # type: ignore[arg-type]
        can_execute_now=result.can_execute_now,
        action_required_message=result.action_required_message,
    )


@router.post("/prompt-refinement/apply", response_model=PromptRefinementApplyResponse)
def apply_prompt_refinement(
    payload: PromptRefinementApplyRequest,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptRefinementApplyResponse:
    result = PromptRefinementAssistantService(
        shared_session=shared_session,
        operational_session=operational_session,
    ).apply(
        token_id=token_scope.token_id,
        automation_id=payload.automation_id,
        corrected_prompt=payload.corrected_prompt,
        apply_prompt_update=payload.apply_prompt_update,
        apply_schema_update=payload.apply_schema_update,
        proposed_output_schema=payload.proposed_output_schema,
        create_new_prompt_version=payload.create_new_prompt_version,
        confirm_apply=payload.confirm_apply,
    )
    return PromptRefinementApplyResponse(
        automation=PromptRefinementApplyAutomationResponse(
            id=result.automation_id,
            name=result.automation_name,
            is_active=result.automation_is_active,
            output_schema=result.output_schema,
        ),
        prompt_update_applied=result.prompt_update_applied,
        schema_update_applied=result.schema_update_applied,
        updated_prompt_id=result.updated_prompt_id,
        updated_prompt_version=result.updated_prompt_version,
        applied_prompt_text=result.applied_prompt_text,
        previous_result_fields=result.previous_result_fields,
        current_result_fields=result.current_result_fields,
        suggested_result_fields=result.suggested_result_fields,
        fields_added=result.fields_added,
        fields_removed=result.fields_removed,
        can_execute_now=result.can_execute_now,
        action_required_message=result.action_required_message,
        change_summary=result.change_summary,
    )


@router.post("/prompt-refinement/advanced-preview", response_model=PromptRefinementAdvancedPreviewResponse)
def advanced_preview_prompt_refinement(
    payload: PromptRefinementAdvancedPreviewRequest,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptRefinementAdvancedPreviewResponse:
    result = PromptRefinementAssistantService(
        shared_session=shared_session,
        operational_session=operational_session,
    ).advanced_preview(
        token_id=token_scope.token_id,
        automation_id=payload.automation_id,
        raw_prompt=payload.raw_prompt,
        expected_result_description=payload.expected_result_description,
    )
    return PromptRefinementAdvancedPreviewResponse(
        automation_id=result.automation_id,
        raw_prompt=result.raw_prompt,
        corrected_prompt=result.corrected_prompt,
        prompt_original=result.prompt_original,
        current_prompt_summary=result.current_prompt_summary,
        prompt_change_summary=result.prompt_change_summary,
        current_result_fields=result.current_result_fields,
        suggested_result_fields=result.suggested_result_fields,
        fields_to_add=result.fields_to_add,
        fields_to_remove=result.fields_to_remove,
        current_output_schema=result.current_output_schema,
        proposed_output_schema=result.proposed_output_schema,
        schema_diff=PromptRefinementSchemaDiff.model_validate(result.schema_diff),
        placeholder_analysis=PromptRefinementPlaceholderAnalysis.model_validate(result.placeholder_analysis),
        mapping_analysis=PromptRefinementMappingAnalysis.model_validate(result.mapping_analysis),
        confidence_level=result.confidence_level,  # type: ignore[arg-type]
        compatibility_status=result.compatibility_status,  # type: ignore[arg-type]
        can_execute_now=result.can_execute_now,
        action_required_message=result.action_required_message,
        review_recommendations=result.review_recommendations,
        technical_warnings=result.technical_warnings,
        safe_apply_options=PromptRefinementSafeApplyOptions.model_validate(result.safe_apply_options),
    )


@router.post("/prompt-refinement/advanced-apply", response_model=PromptRefinementAdvancedApplyResponse)
def advanced_apply_prompt_refinement(
    payload: PromptRefinementAdvancedApplyRequest,
    token_scope: TokenScope = Depends(get_current_token_scope),
    operational_session: Session = Depends(get_operational_session),
    shared_session: Session = Depends(get_shared_session),
) -> PromptRefinementAdvancedApplyResponse:
    result = PromptRefinementAssistantService(
        shared_session=shared_session,
        operational_session=operational_session,
    ).advanced_apply(
        token_id=token_scope.token_id,
        automation_id=payload.automation_id,
        corrected_prompt=payload.corrected_prompt,
        expected_result_description=payload.expected_result_description,
        apply_prompt_update=payload.apply_prompt_update,
        apply_schema_update=payload.apply_schema_update,
        reviewed_output_schema=payload.reviewed_output_schema,
        create_new_prompt_version=payload.create_new_prompt_version,
        confirm_apply=payload.confirm_apply,
        confirm_manual_review=payload.confirm_manual_review,
        allow_field_removals=payload.allow_field_removals,
    )
    return PromptRefinementAdvancedApplyResponse(
        automation=PromptRefinementApplyAutomationResponse(
            id=result.automation_id,
            name=result.automation_name,
            is_active=result.automation_is_active,
            output_schema=result.output_schema,
        ),
        prompt_update_applied=result.prompt_update_applied,
        schema_update_applied=result.schema_update_applied,
        updated_prompt_id=result.updated_prompt_id,
        updated_prompt_version=result.updated_prompt_version,
        applied_prompt_text=result.applied_prompt_text,
        previous_result_fields=result.previous_result_fields,
        current_result_fields=result.current_result_fields,
        suggested_result_fields=result.suggested_result_fields,
        fields_added=result.fields_added,
        fields_removed=result.fields_removed,
        current_output_schema=result.current_output_schema,
        applied_output_schema=result.applied_output_schema,
        schema_diff=PromptRefinementSchemaDiff.model_validate(result.schema_diff),
        placeholder_analysis=PromptRefinementPlaceholderAnalysis.model_validate(result.placeholder_analysis),
        mapping_analysis=PromptRefinementMappingAnalysis.model_validate(result.mapping_analysis),
        confidence_level=result.confidence_level,  # type: ignore[arg-type]
        compatibility_status=result.compatibility_status,  # type: ignore[arg-type]
        can_execute_now=result.can_execute_now,
        action_required_message=result.action_required_message,
        review_recommendations=result.review_recommendations,
        technical_warnings=result.technical_warnings,
        change_summary=result.change_summary,
    )
