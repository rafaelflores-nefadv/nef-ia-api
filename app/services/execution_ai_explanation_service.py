from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.provider_service import ProviderRuntimeSelection

logger = logging.getLogger(__name__)

_RESPONSE_KEYS = ("summary", "reason", "input_issue", "recommendation")

_FALLBACK_PARSE_LABELS = {
    "summary": ("summary", "resumo"),
    "reason": ("reason", "motivo", "razao", "razão"),
    "input_issue": ("input_issue", "problema", "issue"),
    "recommendation": ("recommendation", "recomendacao", "recomendação", "sugestao"),
}


class ExecutionAIExplanationService:
    def generate(
        self,
        *,
        translated_context: str,
        system_prompt: str,
        runtime: ProviderRuntimeSelection,
    ) -> dict[str, str] | None:
        prompt_input = f"{system_prompt.strip()}\n\n---\n\n{translated_context.strip()}"
        try:
            raw_model_metadata = getattr(runtime.model, "config_json", None)
            model_metadata: dict[str, Any] = dict(raw_model_metadata) if isinstance(raw_model_metadata, dict) else {}

            result = runtime.client.execute_prompt(
                prompt=prompt_input,
                model_name=runtime.model.model_slug,
                max_tokens=1024,
                temperature=0.2,
                model_metadata=model_metadata or None,
                client_request_id=None,
            )
            parsed = self._parse_response(getattr(result, "output_text", "") or "")
            if parsed is not None:
                return parsed
            logger.warning("AI explanation response could not be parsed; falling back to rule-based.")
            return None
        except Exception:
            logger.warning("AI explanation call failed; falling back to rule-based.", exc_info=True)
            return None

    def _parse_response(self, text: str) -> dict[str, str] | None:
        text = text.strip()
        if not text:
            return None

        # Try strict JSON block first
        json_text = self._extract_json_block(text)
        if json_text:
            try:
                data = json.loads(json_text)
                if isinstance(data, dict):
                    result = self._extract_known_keys(data)
                    if result:
                        return result
            except json.JSONDecodeError:
                pass

        # Try full text as JSON
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                result = self._extract_known_keys(data)
                if result:
                    return result
        except json.JSONDecodeError:
            pass

        # Fallback: treat full text as the reason field
        if len(text) > 20:
            return {
                "summary": "",
                "reason": text[:1000],
                "input_issue": "",
                "recommendation": "",
            }
        return None

    @staticmethod
    def _extract_json_block(text: str) -> str | None:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start: end + 1]
        return None

    @staticmethod
    def _extract_known_keys(data: dict[str, Any]) -> dict[str, str] | None:
        result: dict[str, str] = {}
        for canonical_key, candidates in _FALLBACK_PARSE_LABELS.items():
            for candidate in candidates:
                if candidate in data:
                    result[canonical_key] = str(data[candidate] or "").strip()
                    break
            else:
                result[canonical_key] = ""
        if any(result.values()):
            return result
        return None
