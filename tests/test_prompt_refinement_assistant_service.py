from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import AppException
from app.repositories.shared import TokenOwnedAutomationRecord, TokenOwnedPromptRecord
from app.services.prompt_refinement_assistant_service import (
    COMPATIBILITY_MANUAL_REVIEW,
    COMPATIBILITY_READY,
    COMPATIBILITY_SCHEMA_UPDATE,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    PromptRefinementAssistantService,
)


class FakeCatalogService:
    def __init__(self) -> None:
        self.automations: dict[tuple[str, str], TokenOwnedAutomationRecord] = {}
        self.prompts: dict[tuple[str, str], TokenOwnedPromptRecord] = {}

    def get_automation_in_scope(self, *, token_id: UUID, automation_id: UUID) -> TokenOwnedAutomationRecord:
        item = self.automations.get((str(token_id), str(automation_id)))
        if item is None:
            raise AppException(
                "Automation not found in token scope.",
                status_code=404,
                code="automation_not_found_in_scope",
                details={"automation_id": str(automation_id)},
            )
        return item

    def list_prompts(
        self,
        *,
        token_id: UUID,
        automation_id: UUID | None = None,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[TokenOwnedPromptRecord]:
        items = [item for (owner, _), item in self.prompts.items() if owner == str(token_id)]
        if automation_id is not None:
            items = [item for item in items if item.automation_id == automation_id]
        if is_active is not None:
            items = [item for item in items if bool(item.is_active) is bool(is_active)]
        items.sort(key=lambda item: (item.created_at, item.version), reverse=True)
        safe_offset = max(int(offset or 0), 0)
        if safe_offset:
            items = items[safe_offset:]
        if limit is not None:
            items = items[: max(int(limit), 0)]
        return items

    def create_prompt(self, *, token_id: UUID, automation_id: UUID, prompt_text: str) -> TokenOwnedPromptRecord:
        current = self.list_prompts(token_id=token_id, automation_id=automation_id, is_active=None, limit=1, offset=0)
        next_version = (current[0].version + 1) if current else 1
        item = TokenOwnedPromptRecord(
            id=uuid4(),
            automation_id=automation_id,
            prompt_text=str(prompt_text or "").strip(),
            version=next_version,
            created_at=datetime.now(timezone.utc),
            is_active=True,
            owner_token_id=token_id,
        )
        self.prompts[(str(token_id), str(item.id))] = item
        return item

    def update_prompt(
        self,
        *,
        token_id: UUID,
        prompt_id: UUID,
        prompt_text: str | None = None,
        automation_id: UUID | None = None,
    ) -> TokenOwnedPromptRecord:
        current = self.prompts.get((str(token_id), str(prompt_id)))
        if current is None:
            raise AppException(
                "Prompt not found in token scope.",
                status_code=404,
                code="prompt_not_found_in_scope",
            )
        updated = replace(
            current,
            prompt_text=str(prompt_text or current.prompt_text).strip(),
            automation_id=automation_id or current.automation_id,
        )
        self.prompts[(str(token_id), str(prompt_id))] = updated
        return updated

    def update_automation(
        self,
        *,
        token_id: UUID,
        automation_id: UUID,
        changes: dict[str, object],
    ) -> TokenOwnedAutomationRecord:
        current = self.get_automation_in_scope(token_id=token_id, automation_id=automation_id)
        updated = replace(
            current,
            output_schema=changes.get("output_schema") if "output_schema" in changes else current.output_schema,
            name=str(changes.get("name") or current.name),
        )
        self.automations[(str(token_id), str(automation_id))] = updated
        return updated


def _build_service() -> tuple[PromptRefinementAssistantService, FakeCatalogService]:
    fake_catalog = FakeCatalogService()
    service = PromptRefinementAssistantService(
        shared_session=object(),  # type: ignore[arg-type]
        operational_session=None,
        catalog_service=fake_catalog,  # type: ignore[arg-type]
    )
    return service, fake_catalog


def _seed_automation(
    fake_catalog: FakeCatalogService,
    *,
    token_id: UUID,
    columns: list[str],
    name: str = "Automacao X",
) -> TokenOwnedAutomationRecord:
    automation = TokenOwnedAutomationRecord(
        id=uuid4(),
        name=name,
        provider_id=uuid4(),
        model_id=uuid4(),
        credential_id=None,
        output_type="spreadsheet_output",
        result_parser="tabular_structured",
        result_formatter="spreadsheet_tabular",
        output_schema={
            "columns": list(columns),
            "ai_output_columns": list(columns),
            "worksheet_name": "resultado",
            "file_name_template": "execution_{execution_id}_resultado.xlsx",
        },
        is_active=True,
        owner_token_id=token_id,
    )
    fake_catalog.automations[(str(token_id), str(automation.id))] = automation
    return automation


def _seed_prompt(
    fake_catalog: FakeCatalogService,
    *,
    token_id: UUID,
    automation_id: UUID,
    prompt_text: str,
) -> TokenOwnedPromptRecord:
    prompt = TokenOwnedPromptRecord(
        id=uuid4(),
        automation_id=automation_id,
        prompt_text=prompt_text,
        version=1,
        created_at=datetime.now(timezone.utc),
        is_active=True,
        owner_token_id=token_id,
    )
    fake_catalog.prompts[(str(token_id), str(prompt.id))] = prompt
    return prompt


def test_preview_without_structural_change() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria", "resumo"])
    _seed_prompt(fake_catalog, token_id=token_id, automation_id=automation.id, prompt_text="Prompt atual")

    result = service.preview(
        token_id=token_id,
        automation_id=automation.id,
        raw_prompt="Classifique e retorne categoria e resumo de cada item.",
        expected_result_description="Quero apenas categoria e resumo.",
    )

    assert result.compatibility_status == COMPATIBILITY_READY
    assert result.fields_to_add == []
    assert result.fields_to_remove == []
    assert result.can_execute_now is True


def test_preview_detects_field_to_add() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria"])

    result = service.preview(
        token_id=token_id,
        automation_id=automation.id,
        raw_prompt="Preciso retornar categoria e prazo.",
        expected_result_description="Incluir categoria e prazo no resultado.",
    )

    assert result.compatibility_status == COMPATIBILITY_SCHEMA_UPDATE
    assert result.fields_to_add == ["prazo"]
    assert result.fields_to_remove == []


def test_preview_detects_fields_to_remove() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(
        fake_catalog,
        token_id=token_id,
        columns=["categoria", "resumo", "pensamento"],
    )

    result = service.preview(
        token_id=token_id,
        automation_id=automation.id,
        raw_prompt="Retorne somente categoria.",
        expected_result_description="Saida final apenas com categoria.",
    )

    assert result.compatibility_status == COMPATIBILITY_SCHEMA_UPDATE
    assert "resumo" in result.fields_to_remove
    assert "pensamento" in result.fields_to_remove


def test_preview_with_low_confidence_requires_manual_review() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria"])

    result = service.preview(
        token_id=token_id,
        automation_id=automation.id,
        raw_prompt="ajusta isso",
        expected_result_description=None,
    )

    assert result.compatibility_status == COMPATIBILITY_MANUAL_REVIEW
    assert result.can_execute_now is False


def test_apply_updates_only_prompt() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria"])
    prompt = _seed_prompt(
        fake_catalog,
        token_id=token_id,
        automation_id=automation.id,
        prompt_text="Prompt antigo",
    )

    result = service.apply(
        token_id=token_id,
        automation_id=automation.id,
        corrected_prompt="Retorne a categoria de cada item.",
        apply_prompt_update=True,
        apply_schema_update=False,
        proposed_output_schema=None,
        create_new_prompt_version=False,
        confirm_apply=True,
    )

    assert result.prompt_update_applied is True
    assert result.schema_update_applied is False
    assert result.updated_prompt_id == prompt.id
    assert result.applied_prompt_text == "Retorne a categoria de cada item."


def test_apply_updates_prompt_and_schema() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria"])
    _seed_prompt(fake_catalog, token_id=token_id, automation_id=automation.id, prompt_text="Prompt antigo")

    preview = service.preview(
        token_id=token_id,
        automation_id=automation.id,
        raw_prompt="Retorne categoria e prazo.",
        expected_result_description="Preciso de categoria e prazo.",
    )

    result = service.apply(
        token_id=token_id,
        automation_id=automation.id,
        corrected_prompt=preview.refined_prompt,
        apply_prompt_update=True,
        apply_schema_update=True,
        proposed_output_schema=preview.proposed_output_schema,
        create_new_prompt_version=True,
        confirm_apply=True,
    )

    assert result.prompt_update_applied is True
    assert result.schema_update_applied is True
    assert "prazo" in result.current_result_fields
    assert "prazo" in result.fields_added


def test_apply_out_of_scope_is_blocked() -> None:
    service, fake_catalog = _build_service()
    token_a = uuid4()
    token_b = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_b, columns=["categoria"])

    with pytest.raises(AppException) as exc_info:
        service.apply(
            token_id=token_a,
            automation_id=automation.id,
            corrected_prompt="Retorne categoria.",
            apply_prompt_update=True,
            apply_schema_update=False,
            proposed_output_schema=None,
            create_new_prompt_version=False,
            confirm_apply=True,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.payload.code == "automation_not_found_in_scope"


def test_advanced_preview_without_structural_change() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria", "resumo"])
    _seed_prompt(fake_catalog, token_id=token_id, automation_id=automation.id, prompt_text="Prompt atual")

    result = service.advanced_preview(
        token_id=token_id,
        automation_id=automation.id,
        raw_prompt="Retorne categoria e resumo para cada linha.",
        expected_result_description="Saida com categoria e resumo.",
    )

    assert result.compatibility_status == COMPATIBILITY_READY
    assert result.schema_diff["added_fields"] == []
    assert result.schema_diff["removed_fields"] == []


def test_advanced_preview_with_field_addition() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria"])

    result = service.advanced_preview(
        token_id=token_id,
        automation_id=automation.id,
        raw_prompt="Retorne categoria e prazo.",
        expected_result_description="Campos: categoria e prazo",
    )

    assert result.compatibility_status == COMPATIBILITY_SCHEMA_UPDATE
    assert result.schema_diff["added_fields"] == ["prazo"]
    assert result.confidence_level == CONFIDENCE_MEDIUM


def test_advanced_preview_with_field_removal() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria", "resumo", "pensamento"])

    result = service.advanced_preview(
        token_id=token_id,
        automation_id=automation.id,
        raw_prompt="Retorne somente categoria.",
        expected_result_description="Saida apenas categoria.",
    )

    assert result.compatibility_status == COMPATIBILITY_SCHEMA_UPDATE
    assert "resumo" in result.schema_diff["removed_fields"]
    assert "pensamento" in result.schema_diff["removed_fields"]


def test_advanced_preview_with_invalid_placeholders() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria"])
    _seed_prompt(
        fake_catalog,
        token_id=token_id,
        automation_id=automation.id,
        prompt_text="Use {{CAMPO_INEXISTENTE}} e retorne categoria.",
    )

    result = service.advanced_preview(
        token_id=token_id,
        automation_id=automation.id,
        raw_prompt="Use {{CAMPO_INEXISTENTE}} e retorne categoria.",
        expected_result_description="categoria",
    )

    assert "CAMPO_INEXISTENTE" in result.placeholder_analysis["invalid_or_unresolved_placeholders"]
    assert len(result.technical_warnings) >= 1


def test_advanced_preview_with_low_confidence() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria"])

    result = service.advanced_preview(
        token_id=token_id,
        automation_id=automation.id,
        raw_prompt="ok",
        expected_result_description=None,
    )

    assert result.compatibility_status == COMPATIBILITY_MANUAL_REVIEW
    assert result.confidence_level == CONFIDENCE_LOW
    assert result.safe_apply_options["requires_manual_review_confirmation"] is True


def test_advanced_apply_prompt_only() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria"])
    prompt = _seed_prompt(fake_catalog, token_id=token_id, automation_id=automation.id, prompt_text="Prompt antigo")

    result = service.advanced_apply(
        token_id=token_id,
        automation_id=automation.id,
        corrected_prompt="Retorne categoria da linha.",
        expected_result_description="categoria",
        apply_prompt_update=True,
        apply_schema_update=False,
        reviewed_output_schema=None,
        create_new_prompt_version=False,
        confirm_apply=True,
        confirm_manual_review=False,
        allow_field_removals=True,
    )

    assert result.prompt_update_applied is True
    assert result.schema_update_applied is False
    assert result.updated_prompt_id == prompt.id


def test_advanced_apply_schema_only() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria"])
    _seed_prompt(fake_catalog, token_id=token_id, automation_id=automation.id, prompt_text="Retorne categoria e prazo.")

    result = service.advanced_apply(
        token_id=token_id,
        automation_id=automation.id,
        corrected_prompt=None,
        expected_result_description=None,
        apply_prompt_update=False,
        apply_schema_update=True,
        reviewed_output_schema={"columns": ["categoria", "prazo"], "ai_output_columns": ["categoria", "prazo"]},
        create_new_prompt_version=False,
        confirm_apply=True,
        confirm_manual_review=False,
        allow_field_removals=True,
    )

    assert result.prompt_update_applied is False
    assert result.schema_update_applied is True
    assert "prazo" in result.current_result_fields


def test_advanced_apply_prompt_and_schema() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria"])
    _seed_prompt(fake_catalog, token_id=token_id, automation_id=automation.id, prompt_text="Prompt antigo")

    result = service.advanced_apply(
        token_id=token_id,
        automation_id=automation.id,
        corrected_prompt="Retorne categoria e prazo.",
        expected_result_description="Campos categoria e prazo.",
        apply_prompt_update=True,
        apply_schema_update=True,
        reviewed_output_schema={"columns": ["categoria", "prazo"], "ai_output_columns": ["categoria", "prazo"]},
        create_new_prompt_version=True,
        confirm_apply=True,
        confirm_manual_review=False,
        allow_field_removals=True,
    )

    assert result.prompt_update_applied is True
    assert result.schema_update_applied is True
    assert "prazo" in result.fields_added


def test_advanced_apply_with_valid_reviewed_output_schema() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria", "resumo"])
    _seed_prompt(fake_catalog, token_id=token_id, automation_id=automation.id, prompt_text="Prompt atual")

    result = service.advanced_apply(
        token_id=token_id,
        automation_id=automation.id,
        corrected_prompt="Retorne apenas categoria.",
        expected_result_description="apenas categoria",
        apply_prompt_update=False,
        apply_schema_update=True,
        reviewed_output_schema={"columns": ["categoria"], "ai_output_columns": ["categoria"]},
        create_new_prompt_version=False,
        confirm_apply=True,
        confirm_manual_review=False,
        allow_field_removals=True,
    )

    assert result.schema_update_applied is True
    assert "resumo" in result.fields_removed


def test_advanced_apply_blocks_invalid_reviewed_output_schema() -> None:
    service, fake_catalog = _build_service()
    token_id = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_id, columns=["categoria"])
    _seed_prompt(fake_catalog, token_id=token_id, automation_id=automation.id, prompt_text="Prompt atual")

    with pytest.raises(AppException) as exc_info:
        service.advanced_apply(
            token_id=token_id,
            automation_id=automation.id,
            corrected_prompt="Retorne categoria",
            expected_result_description="categoria",
            apply_prompt_update=False,
            apply_schema_update=True,
            reviewed_output_schema={"columns": ["categoria"], "worksheet_name": "novo"},
            create_new_prompt_version=False,
            confirm_apply=True,
            confirm_manual_review=False,
            allow_field_removals=True,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.payload.code == "prompt_refinement_reviewed_schema_out_of_scope"


def test_advanced_apply_out_of_scope_is_blocked() -> None:
    service, fake_catalog = _build_service()
    token_a = uuid4()
    token_b = uuid4()
    automation = _seed_automation(fake_catalog, token_id=token_b, columns=["categoria"])

    with pytest.raises(AppException) as exc_info:
        service.advanced_apply(
            token_id=token_a,
            automation_id=automation.id,
            corrected_prompt="Retorne categoria",
            expected_result_description="categoria",
            apply_prompt_update=True,
            apply_schema_update=False,
            reviewed_output_schema=None,
            create_new_prompt_version=False,
            confirm_apply=True,
            confirm_manual_review=False,
            allow_field_removals=True,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.payload.code == "automation_not_found_in_scope"
