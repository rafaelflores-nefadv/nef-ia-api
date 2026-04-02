from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import app.api.routes.external_assistants as external_assistants_route
from app.core.exceptions import AppException
from app.db.session import get_operational_session
from app.db.shared_session import get_shared_session
from app.main import app
from app.services.token_service import ApiTokenService


def _auth_headers(monkeypatch):  # type: ignore[no-untyped-def]
    token_id = uuid4()

    def fake_validate_token(self, raw_token: str):  # type: ignore[no-untyped-def]
        assert raw_token == "ia_live_test_external"
        return SimpleNamespace(token=SimpleNamespace(id=token_id), permissions=[])

    def fake_log_usage(self, **kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(ApiTokenService, "validate_token", fake_validate_token)
    monkeypatch.setattr(ApiTokenService, "log_token_usage", fake_log_usage)
    return {"Authorization": "Bearer ia_live_test_external"}


def _override_sessions() -> None:
    def override_shared_session():  # type: ignore[no-untyped-def]
        yield object()

    def override_operational_session():  # type: ignore[no-untyped-def]
        yield object()

    app.dependency_overrides[get_shared_session] = override_shared_session
    app.dependency_overrides[get_operational_session] = override_operational_session


def test_external_assistant_preview_and_apply_routes(monkeypatch) -> None:
    headers = _auth_headers(monkeypatch)
    _override_sessions()

    automation_id = uuid4()

    class FakePromptRefinementAssistantService:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.kwargs = kwargs

        def preview(self, **kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                automation_id=kwargs["automation_id"],
                prompt_original="Prompt atual",
                prompt_received=kwargs["raw_prompt"],
                refined_prompt="Prompt refinado",
                current_result_fields=["categoria"],
                suggested_result_fields=["categoria", "prazo"],
                fields_to_add=["prazo"],
                fields_to_remove=[],
                proposed_output_schema={"columns": ["categoria", "prazo"], "ai_output_columns": ["categoria", "prazo"]},
                compatibility_status="ready_with_schema_update_required",
                can_execute_now=False,
                action_required_message="Atualize os campos antes de executar.",
            )

        def apply(self, **kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                automation_id=kwargs["automation_id"],
                automation_name="Automacao",
                automation_is_active=True,
                output_schema=kwargs["proposed_output_schema"],
                prompt_update_applied=True,
                schema_update_applied=True,
                updated_prompt_id=uuid4(),
                updated_prompt_version=2,
                applied_prompt_text=kwargs["corrected_prompt"],
                previous_result_fields=["categoria"],
                current_result_fields=["categoria", "prazo"],
                suggested_result_fields=["categoria", "prazo"],
                fields_added=["prazo"],
                fields_removed=[],
                can_execute_now=True,
                action_required_message="Pronto para executar.",
                change_summary="Prompt refinado aplicado. Campos de resultado da automacao atualizados.",
            )

        def advanced_preview(self, **kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                automation_id=kwargs["automation_id"],
                raw_prompt=kwargs["raw_prompt"],
                corrected_prompt="Prompt tecnico refinado",
                prompt_original="Prompt atual",
                current_prompt_summary="Resumo prompt atual",
                prompt_change_summary="Prompt refinado expandiu instrucoes em 12 caracteres.",
                current_result_fields=["categoria"],
                suggested_result_fields=["categoria", "prazo"],
                fields_to_add=["prazo"],
                fields_to_remove=[],
                current_output_schema={"columns": ["categoria"], "ai_output_columns": ["categoria"]},
                proposed_output_schema={"columns": ["categoria", "prazo"], "ai_output_columns": ["categoria", "prazo"]},
                schema_diff={
                    "kept_fields": ["categoria"],
                    "added_fields": ["prazo"],
                    "removed_fields": [],
                    "ai_output_columns_current": ["categoria"],
                    "ai_output_columns_suggested": ["categoria", "prazo"],
                    "ai_output_columns_added": ["prazo"],
                    "ai_output_columns_removed": [],
                    "relevant_changes": ["Novos campos de resultado detectados: prazo."],
                    "observations": [],
                },
                placeholder_analysis={
                    "detected_in_corrected_prompt": [],
                    "valid_schema_placeholders": ["CATEGORIA", "PRAZO"],
                    "suggested_placeholders": ["CATEGORIA", "PRAZO"],
                    "recommended_missing_placeholders": ["CATEGORIA", "PRAZO"],
                    "invalid_or_unresolved_placeholders": [],
                    "impact_summary": "Ha placeholders recomendados ausentes no prompt refinado.",
                },
                mapping_analysis={
                    "mappings_preserved": [],
                    "mappings_potentially_affected": [],
                    "mapping_ambiguities": [],
                    "needs_review": False,
                    "impact_summary": "Mappings preservados sem impacto relevante.",
                },
                confidence_level="medium",
                compatibility_status="ready_with_schema_update_required",
                can_execute_now=False,
                action_required_message="Atualize os campos antes de executar.",
                review_recommendations=["Validar novos campos."],
                technical_warnings=["A execucao imediata pode falhar sem aplicar atualizacao de campos de resultado."],
                safe_apply_options={
                    "can_apply_prompt_only": True,
                    "can_apply_schema_only": True,
                    "can_apply_prompt_and_schema": True,
                    "requires_manual_review_confirmation": False,
                },
            )

        def advanced_apply(self, **kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                automation_id=kwargs["automation_id"],
                automation_name="Automacao",
                automation_is_active=True,
                output_schema={"columns": ["categoria", "prazo"], "ai_output_columns": ["categoria", "prazo"]},
                prompt_update_applied=True,
                schema_update_applied=True,
                updated_prompt_id=uuid4(),
                updated_prompt_version=3,
                applied_prompt_text="Prompt tecnico refinado",
                previous_result_fields=["categoria"],
                current_result_fields=["categoria", "prazo"],
                suggested_result_fields=["categoria", "prazo"],
                fields_added=["prazo"],
                fields_removed=[],
                current_output_schema={"columns": ["categoria"], "ai_output_columns": ["categoria"]},
                applied_output_schema={"columns": ["categoria", "prazo"], "ai_output_columns": ["categoria", "prazo"]},
                schema_diff={
                    "kept_fields": ["categoria"],
                    "added_fields": ["prazo"],
                    "removed_fields": [],
                    "ai_output_columns_current": ["categoria"],
                    "ai_output_columns_suggested": ["categoria", "prazo"],
                    "ai_output_columns_added": ["prazo"],
                    "ai_output_columns_removed": [],
                    "relevant_changes": ["Novos campos de resultado detectados: prazo."],
                    "observations": [],
                },
                placeholder_analysis={
                    "detected_in_corrected_prompt": [],
                    "valid_schema_placeholders": ["CATEGORIA", "PRAZO"],
                    "suggested_placeholders": ["CATEGORIA", "PRAZO"],
                    "recommended_missing_placeholders": ["CATEGORIA", "PRAZO"],
                    "invalid_or_unresolved_placeholders": [],
                    "impact_summary": "Ha placeholders recomendados ausentes no prompt refinado.",
                },
                mapping_analysis={
                    "mappings_preserved": [],
                    "mappings_potentially_affected": [],
                    "mapping_ambiguities": [],
                    "needs_review": False,
                    "impact_summary": "Mappings preservados sem impacto relevante.",
                },
                confidence_level="medium",
                compatibility_status="ready_with_schema_update_required",
                can_execute_now=False,
                action_required_message="Atualize os campos antes de executar.",
                review_recommendations=["Validar novos campos."],
                technical_warnings=["A execucao imediata pode falhar sem aplicar atualizacao de campos de resultado."],
                change_summary="Prompt refinado aplicado. Campos de resultado da automacao atualizados.",
            )

    monkeypatch.setattr(
        external_assistants_route,
        "PromptRefinementAssistantService",
        FakePromptRefinementAssistantService,
    )

    try:
        client = TestClient(app)
        preview_response = client.post(
            "/api/v1/external/assistants/prompt-refinement/preview",
            json={
                "automation_id": str(automation_id),
                "raw_prompt": "Retorne categoria e prazo",
                "expected_result_description": "Quero categoria e prazo",
            },
            headers=headers,
        )
        assert preview_response.status_code == 200
        preview_payload = preview_response.json()
        assert preview_payload["fields_to_add"] == ["prazo"]
        assert preview_payload["compatibility_status"] == "ready_with_schema_update_required"

        apply_response = client.post(
            "/api/v1/external/assistants/prompt-refinement/apply",
            json={
                "automation_id": str(automation_id),
                "corrected_prompt": "Prompt refinado",
                "apply_prompt_update": True,
                "apply_schema_update": True,
                "proposed_output_schema": {"columns": ["categoria", "prazo"], "ai_output_columns": ["categoria", "prazo"]},
                "create_new_prompt_version": True,
                "confirm_apply": True,
            },
            headers=headers,
        )
        assert apply_response.status_code == 200
        apply_payload = apply_response.json()
        assert apply_payload["prompt_update_applied"] is True
        assert apply_payload["schema_update_applied"] is True
        assert apply_payload["fields_added"] == ["prazo"]

        advanced_preview_response = client.post(
            "/api/v1/external/assistants/prompt-refinement/advanced-preview",
            json={
                "automation_id": str(automation_id),
                "raw_prompt": "Retorne categoria e prazo",
                "expected_result_description": "Quero categoria e prazo",
            },
            headers=headers,
        )
        assert advanced_preview_response.status_code == 200
        advanced_preview_payload = advanced_preview_response.json()
        assert advanced_preview_payload["confidence_level"] == "medium"
        assert advanced_preview_payload["schema_diff"]["added_fields"] == ["prazo"]

        advanced_apply_response = client.post(
            "/api/v1/external/assistants/prompt-refinement/advanced-apply",
            json={
                "automation_id": str(automation_id),
                "corrected_prompt": "Prompt tecnico refinado",
                "apply_prompt_update": True,
                "apply_schema_update": True,
                "reviewed_output_schema": {"columns": ["categoria", "prazo"], "ai_output_columns": ["categoria", "prazo"]},
                "create_new_prompt_version": True,
                "confirm_apply": True,
                "confirm_manual_review": False,
                "allow_field_removals": True,
            },
            headers=headers,
        )
        assert advanced_apply_response.status_code == 200
        advanced_apply_payload = advanced_apply_response.json()
        assert advanced_apply_payload["schema_update_applied"] is True
        assert advanced_apply_payload["schema_diff"]["added_fields"] == ["prazo"]
    finally:
        app.dependency_overrides.clear()


def test_external_assistant_apply_requires_confirmation(monkeypatch) -> None:
    headers = _auth_headers(monkeypatch)
    _override_sessions()

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/external/assistants/prompt-refinement/apply",
            json={
                "automation_id": str(uuid4()),
                "corrected_prompt": "Prompt refinado",
                "apply_prompt_update": True,
                "apply_schema_update": False,
                "confirm_apply": False,
            },
            headers=headers,
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_external_assistant_preview_respects_token_scope(monkeypatch) -> None:
    headers = _auth_headers(monkeypatch)
    _override_sessions()

    class FakePromptRefinementAssistantService:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.kwargs = kwargs

        def preview(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AppException(
                "Automation not found in token scope.",
                status_code=404,
                code="automation_not_found_in_scope",
                details={"automation_id": str(kwargs["automation_id"])},
            )

    monkeypatch.setattr(
        external_assistants_route,
        "PromptRefinementAssistantService",
        FakePromptRefinementAssistantService,
    )

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/external/assistants/prompt-refinement/preview",
            json={
                "automation_id": str(uuid4()),
                "raw_prompt": "retorne categoria",
            },
            headers=headers,
        )
        assert response.status_code == 404
        payload = response.json()
        assert payload["error"]["code"] == "automation_not_found_in_scope"
    finally:
        app.dependency_overrides.clear()


def test_external_assistant_advanced_apply_reviewed_schema_out_of_scope(monkeypatch) -> None:
    headers = _auth_headers(monkeypatch)
    _override_sessions()

    class FakePromptRefinementAssistantService:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.kwargs = kwargs

        def advanced_apply(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AppException(
                "Reviewed schema exceeded the allowed safe review scope.",
                status_code=422,
                code="prompt_refinement_reviewed_schema_out_of_scope",
                details={"disallowed_keys": ["worksheet_name"]},
            )

    monkeypatch.setattr(
        external_assistants_route,
        "PromptRefinementAssistantService",
        FakePromptRefinementAssistantService,
    )

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/external/assistants/prompt-refinement/advanced-apply",
            json={
                "automation_id": str(uuid4()),
                "apply_prompt_update": False,
                "apply_schema_update": True,
                "reviewed_output_schema": {
                    "columns": ["categoria"],
                    "worksheet_name": "alterado",
                },
                "confirm_apply": True,
                "confirm_manual_review": True,
            },
            headers=headers,
        )
        assert response.status_code == 422
        payload = response.json()
        assert payload["error"]["code"] == "prompt_refinement_reviewed_schema_out_of_scope"
    finally:
        app.dependency_overrides.clear()
