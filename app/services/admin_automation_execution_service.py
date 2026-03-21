from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.constants import ExecutionStatus
from app.core.config import get_settings
from app.models.operational import DjangoAiApiToken, DjangoAiApiTokenPermission
from app.repositories.operational import ProviderModelRepository, ProviderRepository, QueueJobRepository
from app.repositories.shared import SharedAnalysisRepository, SharedAutomationRepository
from app.services.execution_service import ExecutionService
from app.services.file_service import DownloadableFile, FileService
from app.services.prompt_test_runtime_service import (
    PromptTestManualAutomationContext,
    PromptTestRuntimeContext,
    PromptTestRuntimeService,
)

settings = get_settings()


@dataclass(slots=True, frozen=True)
class AdminAutomationExecutionStartResult:
    automation_id: UUID
    analysis_request_id: UUID
    request_file_id: UUID
    execution_id: UUID
    queue_job_id: UUID
    status: ExecutionStatus
    prompt_version: int
    prompt_override_applied: bool


class AdminAutomationExecutionService:
    def __init__(
        self,
        *,
        operational_session: Session,
        shared_session: Session,
    ) -> None:
        self.operational_session = operational_session
        self.shared_session = shared_session
        self.shared_automations = SharedAutomationRepository(shared_session)
        self.shared_analysis = SharedAnalysisRepository(shared_session)
        self.providers = ProviderRepository(operational_session)
        self.provider_models = ProviderModelRepository(operational_session)
        self.queue_jobs = QueueJobRepository(operational_session)
        self.file_service = FileService(
            operational_session=operational_session,
            shared_session=shared_session,
        )
        self.execution_service = ExecutionService(
            operational_session=operational_session,
            shared_session=shared_session,
        )
        self.test_prompt_runtime = PromptTestRuntimeService(shared_session)

    @staticmethod
    def _is_test_automation(
        *,
        automation_name: str | None,
        automation_slug: str | None,
        is_test_marker: bool | None = None,
    ) -> bool:
        if is_test_marker is True:
            return True
        configured_slug = str(settings.test_prompts_automation_slug or "").strip().lower()
        configured_name = str(settings.test_prompts_automation_name or "").strip().lower()
        normalized_slug = str(automation_slug or "").strip().lower()
        normalized_name = str(automation_name or "").strip().lower()
        if normalized_slug.startswith("test-prompt-"):
            return True
        if normalized_name.startswith("teste - ") or normalized_name.startswith("[teste]"):
            return True
        if configured_slug and normalized_slug == configured_slug:
            return True
        if configured_name and normalized_name == configured_name:
            return True
        return False

    @staticmethod
    def _summarize_prompt_text(prompt_text: str, *, limit: int = 220) -> str:
        normalized = " ".join(str(prompt_text or "").split()).strip()
        if not normalized:
            return ""
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit].rstrip()}..."

    def list_automation_runtimes(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for automation in self.shared_automations.list_automations():
            runtime = self.shared_automations.get_runtime_config_for_automation(automation.id)
            runtime_target = self.shared_automations.get_runtime_target_for_automation(automation.id)
            latest_request = self.shared_analysis.get_latest_request_by_automation_id(automation.id)
            prompt_text = runtime.prompt_text if runtime is not None else ""
            resolved_slug = (
                runtime.automation_slug
                if runtime is not None and runtime.automation_slug is not None
                else runtime_target.automation_slug if runtime_target is not None else None
            )
            resolved_provider_slug = (
                runtime.provider_slug
                if runtime is not None and runtime.provider_slug is not None
                else runtime_target.provider_slug if runtime_target is not None else None
            )
            resolved_model_slug = (
                runtime.model_slug
                if runtime is not None and runtime.model_slug is not None
                else runtime_target.model_slug if runtime_target is not None else None
            )
            is_test_marker = (
                runtime.is_test_automation
                if runtime is not None and runtime.is_test_automation is not None
                else runtime_target.is_test_automation if runtime_target is not None else None
            )
            items.append(
                {
                    "automation_id": automation.id,
                    "automation_name": str(automation.name or "").strip() or str(automation.id),
                    "automation_slug": resolved_slug,
                    "automation_is_active": bool(automation.is_active),
                    "prompt_available": runtime is not None,
                    "prompt_version": runtime.prompt_version if runtime is not None else None,
                    "prompt_summary": self._summarize_prompt_text(prompt_text),
                    "provider_slug": resolved_provider_slug,
                    "model_slug": resolved_model_slug,
                    "latest_analysis_request_id": latest_request.id if latest_request is not None else None,
                    "is_test_automation": self._is_test_automation(
                        automation_name=str(automation.name or "").strip() or None,
                        automation_slug=resolved_slug,
                        is_test_marker=is_test_marker,
                    ),
                }
            )
        return items

    def get_automation_runtime(self, *, automation_id: UUID) -> dict[str, Any]:
        automation = self.shared_automations.get_automation_by_id(automation_id)
        if automation is None:
            raise AppException(
                "Automation not found.",
                status_code=404,
                code="automation_not_found",
                details={"automation_id": str(automation_id)},
            )
        runtime = self.shared_automations.get_runtime_config_for_automation(automation_id)
        runtime_target = self.shared_automations.get_runtime_target_for_automation(automation_id)
        latest_request = self.shared_analysis.get_latest_request_by_automation_id(automation_id)
        prompt_text = runtime.prompt_text if runtime is not None else ""
        resolved_slug = (
            runtime.automation_slug
            if runtime is not None and runtime.automation_slug is not None
            else runtime_target.automation_slug if runtime_target is not None else None
        )
        resolved_provider_slug = (
            runtime.provider_slug
            if runtime is not None and runtime.provider_slug is not None
            else runtime_target.provider_slug if runtime_target is not None else None
        )
        resolved_model_slug = (
            runtime.model_slug
            if runtime is not None and runtime.model_slug is not None
            else runtime_target.model_slug if runtime_target is not None else None
        )
        is_test_marker = (
            runtime.is_test_automation
            if runtime is not None and runtime.is_test_automation is not None
            else runtime_target.is_test_automation if runtime_target is not None else None
        )
        return {
            "automation_id": automation.id,
            "automation_name": str(automation.name or "").strip() or str(automation.id),
            "automation_slug": resolved_slug,
            "automation_is_active": bool(automation.is_active),
            "prompt_available": runtime is not None,
            "prompt_version": runtime.prompt_version if runtime is not None else None,
            "prompt_summary": self._summarize_prompt_text(prompt_text),
            "prompt_text": prompt_text,
            "provider_slug": resolved_provider_slug,
            "model_slug": resolved_model_slug,
            "latest_analysis_request_id": latest_request.id if latest_request is not None else None,
            "is_test_automation": self._is_test_automation(
                automation_name=str(automation.name or "").strip() or None,
                automation_slug=resolved_slug,
                is_test_marker=is_test_marker,
            ),
        }

    def list_active_provider_models(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for provider in self.providers.list_active():
            models = self.provider_models.list_by_provider(provider.id)
            for model in models:
                if not model.is_active:
                    continue
                items.append(
                    {
                        "provider_id": provider.id,
                        "provider_name": str(provider.name or "").strip() or str(provider.id),
                        "provider_slug": str(provider.slug or "").strip().lower(),
                        "model_id": model.id,
                        "model_name": str(model.model_name or "").strip() or str(model.id),
                        "model_slug": str(model.model_slug or "").strip().lower(),
                    }
                )
        return sorted(
            items,
            key=lambda item: (
                str(item["provider_name"]).lower(),
                str(item["model_name"]).lower(),
            ),
        )

    def create_test_automation(
        self,
        *,
        name: str,
        provider_id: UUID,
        model_id: UUID,
    ) -> dict[str, Any]:
        provider = self.providers.get_by_id(provider_id)
        if provider is None or not provider.is_active:
            raise AppException(
                "Provider not found or inactive.",
                status_code=404,
                code="provider_not_found",
                details={"provider_id": str(provider_id)},
            )
        model = self.provider_models.get_by_id(model_id)
        if model is None or not model.is_active:
            raise AppException(
                "Provider model not found or inactive.",
                status_code=404,
                code="provider_model_not_found",
                details={"model_id": str(model_id)},
            )
        if model.provider_id != provider.id:
            raise AppException(
                "Selected model does not belong to selected provider.",
                status_code=422,
                code="provider_model_mismatch",
                details={
                    "provider_id": str(provider_id),
                    "model_id": str(model_id),
                },
            )

        context: PromptTestManualAutomationContext = self.test_prompt_runtime.create_manual_test_automation(
            automation_name=name,
            provider_slug=str(provider.slug or "").strip().lower(),
            model_slug=str(model.model_slug or "").strip().lower(),
            provider_id=provider.id,
            model_id=model.id,
        )
        return {
            "automation_id": context.automation_id,
            "automation_name": context.automation_name,
            "automation_slug": context.automation_slug,
            "analysis_request_id": context.analysis_request_id,
            "provider_slug": context.provider_slug,
            "model_slug": context.model_slug,
            "is_test_automation": True,
        }

    def get_prompt_test_runtime(self) -> dict[str, Any]:
        context: PromptTestRuntimeContext = self.test_prompt_runtime.ensure_runtime_context()
        provider_slug = context.provider_slug
        model_slug = context.model_slug
        automation_name = context.automation_name
        automation_slug = context.automation_slug
        automation_id = context.automation_id
        analysis_request_id = context.analysis_request_id

        if not provider_slug or not model_slug:
            default_runtime = self._resolve_default_provider_model_for_tests()
            if default_runtime is not None:
                configured = self.test_prompt_runtime.create_manual_test_automation(
                    automation_name=automation_name,
                    provider_slug=default_runtime["provider_slug"],
                    model_slug=default_runtime["model_slug"],
                    provider_id=default_runtime["provider_id"],
                    model_id=default_runtime["model_id"],
                )
                provider_slug = configured.provider_slug
                model_slug = configured.model_slug
                automation_name = configured.automation_name
                automation_slug = configured.automation_slug
                automation_id = configured.automation_id
                analysis_request_id = configured.analysis_request_id

        return {
            "automation_id": automation_id,
            "automation_name": automation_name,
            "automation_slug": automation_slug,
            "analysis_request_id": analysis_request_id,
            "provider_slug": str(provider_slug or "").strip().lower(),
            "model_slug": str(model_slug or "").strip().lower(),
            "is_test_automation": True,
        }

    def _resolve_default_provider_model_for_tests(self) -> dict[str, Any] | None:
        available = self.list_active_provider_models()
        if not available:
            return None
        selected = available[0]
        return {
            "provider_id": selected["provider_id"],
            "model_id": selected["model_id"],
            "provider_slug": str(selected["provider_slug"] or "").strip().lower(),
            "model_slug": str(selected["model_slug"] or "").strip().lower(),
        }

    @staticmethod
    def _build_admin_token_and_permissions(
        *,
        actor_user_id: UUID,
        automation_id: UUID,
    ) -> tuple[DjangoAiApiToken, list[DjangoAiApiTokenPermission]]:
        token = DjangoAiApiToken(
            id=uuid.uuid4(),
            name="admin-panel-runtime",
            token_hash="admin-panel-runtime",
            is_active=True,
            expires_at=None,
            created_by_user_id=actor_user_id,
        )
        permissions = [
            DjangoAiApiTokenPermission(
                token_id=token.id,
                automation_id=automation_id,
                provider_id=None,
                allow_execution=True,
                allow_file_upload=True,
            )
        ]
        return token, permissions

    def start_execution_for_automation(
        self,
        *,
        automation_id: UUID,
        upload_file: UploadFile,
        prompt_override: str | None,
        actor_user_id: UUID,
        ip_address: str | None,
        correlation_id: str | None = None,
    ) -> AdminAutomationExecutionStartResult:
        automation = self.shared_automations.get_automation_by_id(automation_id)
        test_automation = None
        if automation is None:
            test_automation = self.test_prompt_runtime.get_test_automation_by_id(automation_id)
        if automation is None and test_automation is None:
            raise AppException(
                "Automation not found.",
                status_code=404,
                code="automation_not_found",
                details={"automation_id": str(automation_id)},
            )

        normalized_prompt_override = str(prompt_override or "").strip() or None
        runtime = self.shared_automations.get_runtime_config_for_automation(automation_id) if automation is not None else None
        if runtime is None and not normalized_prompt_override:
            raise AppException(
                "Prompt not found for execution and no prompt_override was provided.",
                status_code=404,
                code="prompt_not_found",
                details={"automation_id": str(automation_id)},
            )

        latest_request = self.shared_analysis.get_latest_request_by_automation_id(automation_id)
        if latest_request is None:
            raise AppException(
                "No analysis_request available for selected automation.",
                status_code=422,
                code="analysis_request_not_found_for_automation",
                details={"automation_id": str(automation_id)},
            )

        admin_token, permissions = self._build_admin_token_and_permissions(
            actor_user_id=actor_user_id,
            automation_id=automation_id,
        )

        request_file = self.file_service.upload_request_file(
            analysis_request_id=latest_request.id,
            upload_file=upload_file,
            api_token=admin_token,
            token_permissions=permissions,
            ip_address=ip_address,
        )
        execution = self.execution_service.create_execution(
            analysis_request_id=latest_request.id,
            request_file_id=request_file.id,
            prompt_override=normalized_prompt_override,
            api_token=admin_token,
            token_permissions=permissions,
            ip_address=ip_address,
            correlation_id=correlation_id,
        )
        return AdminAutomationExecutionStartResult(
            automation_id=automation_id,
            analysis_request_id=latest_request.id,
            request_file_id=request_file.id,
            execution_id=execution.execution_id,
            queue_job_id=execution.queue_job_id,
            status=execution.status,
            prompt_version=runtime.prompt_version if runtime is not None else 0,
            prompt_override_applied=bool(normalized_prompt_override),
        )

    def get_execution_status_for_admin(self, *, execution_id: UUID, actor_user_id: UUID) -> dict[str, Any]:
        shared_execution = self.shared_analysis.get_execution_by_id(execution_id)
        if shared_execution is None:
            raise AppException(
                "Execution not found.",
                status_code=404,
                code="execution_not_found",
                details={"execution_id": str(execution_id)},
            )
        shared_request = self.shared_analysis.get_request_by_id(shared_execution.analysis_request_id)
        if shared_request is None:
            raise AppException(
                "Related analysis request not found.",
                status_code=404,
                code="analysis_request_not_found",
                details={"analysis_request_id": str(shared_execution.analysis_request_id)},
            )

        _, permissions = self._build_admin_token_and_permissions(
            actor_user_id=actor_user_id,
            automation_id=shared_request.automation_id,
        )
        result = self.execution_service.get_execution_status(
            execution_id=execution_id,
            token_permissions=permissions,
        )
        request_file_id: UUID | None = None
        request_file_name: str | None = None
        prompt_override_applied = False
        latest_queue_job = self.queue_jobs.get_latest_by_execution_id(execution_id)
        if latest_queue_job is not None:
            prompt_override_applied = bool(str(latest_queue_job.prompt_override_text or "").strip())
            if latest_queue_job.request_file_id is not None:
                request_file = self.file_service.request_files.get_by_id(latest_queue_job.request_file_id)
                request_file_id = latest_queue_job.request_file_id
                if request_file is not None:
                    request_file_name = request_file.file_name

        return {
            "execution_id": result.execution_id,
            "analysis_request_id": shared_execution.analysis_request_id,
            "automation_id": shared_request.automation_id,
            "request_file_id": request_file_id,
            "request_file_name": request_file_name,
            "prompt_override_applied": prompt_override_applied,
            "status": result.status,
            "progress": result.progress,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "error_message": result.error_message,
            "created_at": result.created_at,
            "checked_at": datetime.now(timezone.utc),
        }

    def get_execution_file_for_admin_download(
        self,
        *,
        file_id: UUID,
        actor_user_id: UUID,
    ) -> DownloadableFile:
        execution_file = self.file_service.execution_files.get_by_id(file_id)
        if execution_file is None:
            raise AppException(
                "Execution file not found.",
                status_code=404,
                code="execution_file_not_found",
                details={"file_id": str(file_id)},
            )

        shared_execution = self.shared_analysis.get_execution_by_id(execution_file.execution_id)
        if shared_execution is None:
            raise AppException(
                "Related execution not found.",
                status_code=404,
                code="analysis_execution_not_found",
                details={"execution_id": str(execution_file.execution_id)},
            )
        shared_request = self.shared_analysis.get_request_by_id(shared_execution.analysis_request_id)
        if shared_request is None:
            raise AppException(
                "Related analysis request not found.",
                status_code=404,
                code="analysis_request_not_found",
                details={"analysis_request_id": str(shared_execution.analysis_request_id)},
            )

        _, permissions = self._build_admin_token_and_permissions(
            actor_user_id=actor_user_id,
            automation_id=shared_request.automation_id,
        )
        return self.file_service.get_execution_file_for_download(
            file_id=file_id,
            token_permissions=permissions,
        )
