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
from app.repositories.operational import QueueJobRepository
from app.repositories.shared import SharedAnalysisRepository, SharedAutomationRepository
from app.services.execution_service import ExecutionService
from app.services.file_service import DownloadableFile, FileService
from app.services.prompt_test_runtime_service import PromptTestRuntimeContext, PromptTestRuntimeService

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
    def _is_test_automation(*, automation_name: str | None, automation_slug: str | None) -> bool:
        configured_slug = str(settings.test_prompts_automation_slug or "").strip().lower()
        configured_name = str(settings.test_prompts_automation_name or "").strip().lower()
        normalized_slug = str(automation_slug or "").strip().lower()
        normalized_name = str(automation_name or "").strip().lower()
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
            latest_request = self.shared_analysis.get_latest_request_by_automation_id(automation.id)
            prompt_text = runtime.prompt_text if runtime is not None else ""
            items.append(
                {
                    "automation_id": automation.id,
                    "automation_name": str(automation.name or "").strip() or str(automation.id),
                    "automation_slug": runtime.automation_slug if runtime is not None else None,
                    "automation_is_active": bool(automation.is_active),
                    "prompt_available": runtime is not None,
                    "prompt_version": runtime.prompt_version if runtime is not None else None,
                    "prompt_summary": self._summarize_prompt_text(prompt_text),
                    "provider_slug": runtime.provider_slug if runtime is not None else None,
                    "model_slug": runtime.model_slug if runtime is not None else None,
                    "latest_analysis_request_id": latest_request.id if latest_request is not None else None,
                    "is_test_automation": self._is_test_automation(
                        automation_name=str(automation.name or "").strip() or None,
                        automation_slug=runtime.automation_slug if runtime is not None else None,
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
        latest_request = self.shared_analysis.get_latest_request_by_automation_id(automation_id)
        prompt_text = runtime.prompt_text if runtime is not None else ""
        return {
            "automation_id": automation.id,
            "automation_name": str(automation.name or "").strip() or str(automation.id),
            "automation_slug": runtime.automation_slug if runtime is not None else None,
            "automation_is_active": bool(automation.is_active),
            "prompt_available": runtime is not None,
            "prompt_version": runtime.prompt_version if runtime is not None else None,
            "prompt_summary": self._summarize_prompt_text(prompt_text),
            "prompt_text": prompt_text,
            "provider_slug": runtime.provider_slug if runtime is not None else None,
            "model_slug": runtime.model_slug if runtime is not None else None,
            "latest_analysis_request_id": latest_request.id if latest_request is not None else None,
            "is_test_automation": self._is_test_automation(
                automation_name=str(automation.name or "").strip() or None,
                automation_slug=runtime.automation_slug if runtime is not None else None,
            ),
        }

    def ensure_test_prompt_runtime(self) -> dict[str, Any]:
        context: PromptTestRuntimeContext = self.test_prompt_runtime.ensure_runtime_context()
        return {
            "automation_id": context.automation_id,
            "automation_name": context.automation_name,
            "automation_slug": context.automation_slug,
            "analysis_request_id": context.analysis_request_id,
            "created_automation": context.created_automation,
            "created_analysis_request": context.created_analysis_request,
        }

    def start_execution_for_test_prompt(
        self,
        *,
        upload_file: UploadFile,
        prompt_override: str | None,
        actor_user_id: UUID,
        ip_address: str | None,
        correlation_id: str | None = None,
    ) -> AdminAutomationExecutionStartResult:
        runtime_context = self.test_prompt_runtime.ensure_runtime_context()
        return self.start_execution_for_automation(
            automation_id=runtime_context.automation_id,
            upload_file=upload_file,
            prompt_override=prompt_override,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            correlation_id=correlation_id,
        )

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
        if automation is None:
            raise AppException(
                "Automation not found.",
                status_code=404,
                code="automation_not_found",
                details={"automation_id": str(automation_id)},
            )

        normalized_prompt_override = str(prompt_override or "").strip() or None
        runtime = self.shared_automations.get_runtime_config_for_automation(automation_id)
        if runtime is None and not normalized_prompt_override:
            raise AppException(
                "Official automation prompt not found.",
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
