from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from .api_client import ApiResponse, FastAPIClient

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

    from prompts.models import AIPrompt


class PromptTestsServiceError(Exception):
    pass


class PromptTestsService:
    def __init__(self):
        self.client = FastAPIClient()
        self.admin_token = self.client.admin_token

    @staticmethod
    def _extract_error_message(result: ApiResponse) -> str:
        if isinstance(result.data, dict):
            error_payload = result.data.get("error")
            if isinstance(error_payload, dict):
                payload_message = str(error_payload.get("message") or "").strip()
                if payload_message:
                    return payload_message
        return str(result.error or "").strip()

    def start_prompt_test(
        self,
        *,
        prompt: AIPrompt,
        uploaded_file: UploadedFile,
    ) -> dict[str, Any]:
        provider_slug = str(prompt.ai_model.provider.slug or "").strip().lower()
        model_slug = str(prompt.ai_model.slug or "").strip().lower()
        prompt_text = str(prompt.content or "").strip()
        prompt_title = str(prompt.title or "").strip()

        if not provider_slug:
            raise PromptTestsServiceError("Provider do modelo selecionado e invalido.")
        if not model_slug:
            raise PromptTestsServiceError("Modelo do prompt selecionado e invalido.")
        if not prompt_text:
            raise PromptTestsServiceError("O prompt selecionado nao possui conteudo valido.")

        file_name = str(getattr(uploaded_file, "name", "") or "").strip()
        if not file_name:
            raise PromptTestsServiceError("Arquivo invalido para teste de prompt.")

        file_content = uploaded_file.read()
        if not file_content:
            raise PromptTestsServiceError("O arquivo enviado esta vazio.")

        content_type = str(getattr(uploaded_file, "content_type", "") or "").strip()
        if not content_type:
            content_type = "application/octet-stream"

        result = self.client.request_multipart(
            method="POST",
            path="/api/v1/admin/prompt-tests",
            data={
                "prompt_title": prompt_title,
                "prompt_text": prompt_text,
                "provider_slug": provider_slug,
                "model_slug": model_slug,
            },
            files={
                "file": (
                    file_name,
                    file_content,
                    content_type,
                )
            },
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success or not isinstance(result.data, dict):
            message = self._extract_error_message(result)
            raise PromptTestsServiceError(
                message
                or f"Nao foi possivel iniciar o teste de prompt (HTTP {result.status_code})."
            )

        payload = result.data
        prompt_test_id = str(payload.get("id") or "").strip()
        if not prompt_test_id:
            raise PromptTestsServiceError("FastAPI nao retornou identificador do teste de prompt.")

        return payload

    def get_prompt_test_status(self, *, prompt_test_id: UUID) -> dict[str, Any]:
        result = self.client.request_json(
            method="GET",
            path=f"/api/v1/admin/prompt-tests/{prompt_test_id}",
            headers=self.client.get_admin_headers(),
            expect_dict=True,
        )
        if not result.is_success or not isinstance(result.data, dict):
            message = self._extract_error_message(result)
            raise PromptTestsServiceError(
                message
                or f"Nao foi possivel consultar o teste de prompt (HTTP {result.status_code})."
            )
        return result.data
