from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable


SIMPLE_EXPLANATION_COLUMN = "Explicação simplificada"
PENDING_CTR_LABEL = "Análise pendente da CTR"
CONTROLLED_INVALID_JSON_MESSAGE = "Resposta estruturada inválida retornada pela automação."

_WARNING_READABLE: dict[str, str] = {
    "input_description_insufficient": "descrição da publicação estava incompleta ou insuficiente",
    "prompt_placeholder_unresolved": "instrução da automação ficou incompleta durante a montagem",
    "provider_invalid_json_output": "resposta retornou em formato incompatível com a estrutura esperada",
    "tabular_parser_invalid_output": "resposta retornou em formato incompatível com a estrutura esperada",
}


@dataclass(slots=True, frozen=True)
class SimpleExplanation:
    summary: str
    reason: str
    input_issue: str
    recommendation: str

    def as_dict(self) -> dict[str, str]:
        return {
            "summary": self.summary,
            "reason": self.reason,
            "input_issue": self.input_issue,
            "recommendation": self.recommendation,
        }


@dataclass(slots=True)
class TabularPostProcessingResult:
    normalized_output: dict[str, Any]
    row_explanation: str
    warnings: list[str]
    errors: list[str]
    detected_input_issue: str | None = None


class ExecutionSimpleExplanationService:
    def build_translated_debug_context(
        self,
        *,
        data_analyzed: Any,
        final_result: Any,
        technical_debug: Any,
        warnings: Iterable[Any] | None,
        errors: Iterable[Any] | None,
    ) -> str:
        warning_tokens = self._normalize_messages(warnings)
        error_tokens = self._normalize_messages(errors)
        debug_tokens = self._collect_debug_signals(technical_debug)

        lines: list[str] = []

        if isinstance(data_analyzed, list) and data_analyzed:
            lines.append("Dados analisados:")
            for item in data_analyzed[:5]:
                if isinstance(item, dict):
                    for key, value in list(item.items())[:6]:
                        text = str(value or "").strip()
                        if text:
                            lines.append(f"  - {key}: {text[:300]}")
                elif item is not None:
                    lines.append(f"  - {str(item)[:300]}")
        elif isinstance(data_analyzed, dict):
            lines.append("Dados analisados:")
            for key, value in list(data_analyzed.items())[:6]:
                text = str(value or "").strip()
                if text:
                    lines.append(f"  - {key}: {text[:300]}")

        if final_result is not None:
            lines.append("")
            lines.append("Resultado gerado:")
            if isinstance(final_result, list):
                for item in final_result[:5]:
                    if isinstance(item, dict):
                        for key, value in list(item.items())[:6]:
                            lines.append(f"  - {key}: {str(value or '') or 'não identificado'}")
            elif isinstance(final_result, dict):
                for key, value in list(final_result.items())[:6]:
                    lines.append(f"  - {key}: {str(value or '') or 'não identificado'}")
            else:
                lines.append(f"  {str(final_result)[:500]}")

        input_issue = self._detect_input_issue(
            data_analyzed=data_analyzed,
            final_result=final_result,
            warning_tokens=warning_tokens,
            error_tokens=error_tokens,
            debug_tokens=debug_tokens,
        )

        situation_lines: list[str] = []
        if self._result_looks_pending(final_result):
            situation_lines.append("resultado classificado como análise pendente")
        if input_issue:
            situation_lines.append(input_issue)
        for token in warning_tokens[:3]:
            readable = _WARNING_READABLE.get(token)
            if readable:
                situation_lines.append(readable)
        if error_tokens:
            situation_lines.append("ocorreu uma inconsistência durante o processamento")

        if situation_lines:
            lines.append("")
            lines.append("Situação identificada:")
            for item in situation_lines:
                lines.append(f"  - {item}")

        return "\n".join(lines)

    def generate_simple_debug_explanation(
        self,
        *,
        data_analyzed: Any,
        prompt_used: str | None,
        final_result: Any,
        technical_debug: Any,
        warnings: Iterable[Any] | None,
        errors: Iterable[Any] | None,
        status: str | None,
    ) -> dict[str, str]:
        warning_tokens = self._normalize_messages(warnings)
        error_tokens = self._normalize_messages(errors)
        debug_tokens = self._collect_debug_signals(technical_debug)
        input_issue = self._detect_input_issue(
            data_analyzed=data_analyzed,
            final_result=final_result,
            warning_tokens=warning_tokens,
            error_tokens=error_tokens,
            debug_tokens=debug_tokens,
        )
        status_text = str(status or "").strip().lower()

        summary = self._build_summary(
            data_analyzed=data_analyzed,
            final_result=final_result,
        )
        reason = self._build_reason(
            status=status_text,
            final_result=final_result,
            input_issue=input_issue,
            warning_tokens=warning_tokens,
            error_tokens=error_tokens,
            debug_tokens=debug_tokens,
        )
        recommendation = self._build_recommendation(
            input_issue=input_issue,
            prompt_used=prompt_used,
            warning_tokens=warning_tokens,
            error_tokens=error_tokens,
            debug_tokens=debug_tokens,
        )
        return SimpleExplanation(
            summary=summary,
            reason=reason,
            input_issue=input_issue,
            recommendation=recommendation,
        ).as_dict()

    def apply_post_response_validations(
        self,
        *,
        row_values: dict[str, Any],
        normalized_output: dict[str, Any],
        json_parse_error: str | None,
    ) -> TabularPostProcessingResult:
        result = {str(key): value for key, value in normalized_output.items()}
        original_has_meaningful_output = self._has_meaningful_structured_output(result)
        warnings: list[str] = []
        errors: list[str] = []
        issue_messages: list[str] = []
        description_keys = (
            "descricao",
            "conteudo",
            "conteúdo",
            "descricao_fato",
            "texto",
            "historico",
            "resumo",
        )

        description = self._extract_first_value(
            row_values,
            description_keys,
        )
        if self._has_any_key(row_values, description_keys) and self._is_insufficient_description(description):
            self._apply_pending_ctr_fallback(result)
            issue_messages.append(
                "A descrição analisada estava vazia ou com informação insuficiente para identificar um comando processual claro."
            )
            warnings.append("input_description_insufficient")

        commitment_value = self._extract_first_value(
            result,
            ("compromissoAnalista", "compromisso_analista"),
        )
        if not self._has_clear_procedural_command(commitment_value):
            self._clear_known_field(result, ("compromissoAnalista", "compromisso_analista"))
            issue_messages.append(
                "Não foi possível identificar um comando processual claro para preencher o compromisso do analista."
            )

        deadline_value = self._extract_first_value(result, ("prazo", "prazo_agendado"))
        if issue_messages and not self._has_identified_deadline(deadline_value):
            self._clear_known_field(result, ("prazo", "prazo_agendado"))

        if json_parse_error and not original_has_meaningful_output:
            errors.append(CONTROLLED_INVALID_JSON_MESSAGE)

        row_explanation = self._build_row_explanation(
            result=result,
            issue_messages=issue_messages,
            errors=errors,
        )
        return TabularPostProcessingResult(
            normalized_output=result,
            row_explanation=row_explanation,
            warnings=warnings,
            errors=errors,
            detected_input_issue=issue_messages[0] if issue_messages else None,
        )

    @staticmethod
    def _normalize_messages(values: Iterable[Any] | None) -> list[str]:
        normalized: list[str] = []
        for item in values or []:
            text = str(item or "").strip()
            if text:
                normalized.append(text)
        return normalized

    def _collect_debug_signals(self, technical_debug: Any) -> list[str]:
        signals: list[str] = []
        if isinstance(technical_debug, dict):
            for key in ("warnings", "errors", "stage_of_failure", "error_type", "provider_error_message"):
                value = technical_debug.get(key)
                if isinstance(value, list):
                    signals.extend(self._normalize_messages(value))
                else:
                    text = str(value or "").strip()
                    if text:
                        signals.append(text)
            chunks = technical_debug.get("chunks")
            if isinstance(chunks, list):
                for chunk in chunks[:10]:
                    if isinstance(chunk, dict):
                        signals.extend(self._collect_debug_signals(chunk))
        elif isinstance(technical_debug, list):
            for item in technical_debug[:25]:
                signals.extend(self._collect_debug_signals(item))
        return signals

    def _detect_input_issue(
        self,
        *,
        data_analyzed: Any,
        final_result: Any,
        warning_tokens: list[str],
        error_tokens: list[str],
        debug_tokens: list[str],
    ) -> str:
        if self._data_looks_empty(data_analyzed):
            return "Os dados enviados estavam vazios ou insuficientes para uma análise conclusiva."
        joined = " ".join([*warning_tokens, *error_tokens, *debug_tokens]).lower()
        if "prompt_placeholder_unresolved" in joined or "placeholder" in joined:
            return "O texto de orientação da automação ficou incompleto durante a montagem da análise."
        if "insuficiente" in joined:
            return "As informações enviadas estavam insuficientes para uma análise conclusiva."
        if "json" in joined and ("invalid" in joined or "malformed" in joined):
            return "A resposta retornou em um formato incompatível com o processamento esperado."
        if "ambig" in joined:
            return "As informações recebidas estavam ambíguas e não permitiram uma interpretação segura."
        if "sem prazo" in joined or "prazo" in joined and "nao" in joined:
            return "Não havia indicação suficiente para identificar prazo na movimentação analisada."
        if self._result_looks_pending(final_result):
            return "As informações analisadas não trouxeram elementos suficientes para definir o encaminhamento com segurança."
        return "O resultado depende da clareza e da completude das informações enviadas para análise."

    def _build_summary(self, *, data_analyzed: Any, final_result: Any) -> str:
        if isinstance(final_result, list):
            total = len(final_result)
            if total == 1:
                return "A automação analisou 1 item da entrada enviada."
            return f"A automação analisou {total} itens da entrada enviada."
        if isinstance(data_analyzed, list):
            total = len(data_analyzed)
            if total == 1:
                return "A automação analisou o item informado."
            return f"A automação analisou {total} itens informados."
        return "A automação analisou a publicação ou o documento informado."

    def _build_reason(
        self,
        *,
        status: str,
        final_result: Any,
        input_issue: str,
        warning_tokens: list[str],
        error_tokens: list[str],
        debug_tokens: list[str],
    ) -> str:
        joined = " ".join([*warning_tokens, *error_tokens, *debug_tokens]).lower()
        if status in {"failed", "error"}:
            return "A análise não foi concluída porque o processamento encontrou uma inconsistência controlada e precisará de nova tentativa com informações mais claras."
        if "json" in joined and ("invalid" in joined or "malformed" in joined):
            return "O resultado ficou pendente porque a resposta retornou em formato incompatível com a estrutura esperada pela automação."
        if self._result_looks_pending(final_result):
            return "O resultado foi marcado como análise pendente porque não foram encontrados elementos suficientes para identificar um comando processual claro."
        if "ambig" in joined:
            return "O resultado foi definido de forma conservadora porque a movimentação analisada permitia mais de uma interpretação possível."
        if "prazo" in joined and "nao" in joined:
            return "O resultado foi gerado sem preenchimento de prazo porque não havia indicação objetiva de data ou termo processual."
        return f"O resultado foi produzido com base nas informações disponíveis. {input_issue}"

    def _build_recommendation(
        self,
        *,
        input_issue: str,
        prompt_used: str | None,
        warning_tokens: list[str],
        error_tokens: list[str],
        debug_tokens: list[str],
    ) -> str:
        joined = " ".join([*warning_tokens, *error_tokens, *debug_tokens]).lower()
        if "placeholder" in joined:
            return "Revise o texto da automação para garantir que todas as instruções estejam completas e alinhadas com os campos da entrada."
        if "json" in joined and ("invalid" in joined or "malformed" in joined):
            return "Tente novamente com uma instrução mais objetiva e com dados estruturados de forma mais completa."
        if self._mentions_incompleteness(input_issue):
            return "Para obter um resultado mais preciso, envie a descrição completa da publicação e destaque o comando processual esperado quando ele existir."
        if prompt_used and len(str(prompt_used).strip()) < 40:
            return "Detalhe melhor a orientação da automação e envie dados mais completos para reduzir ambiguidades na análise."
        return "Para aumentar a precisão, mantenha a instrução objetiva e envie dados completos, claros e diretamente relacionados ao comando processual esperado."

    @staticmethod
    def _extract_first_value(payload: dict[str, Any], keys: Iterable[str]) -> str:
        normalized_map = {
            ExecutionSimpleExplanationService._normalize_key(key): value
            for key, value in payload.items()
        }
        for raw_key in keys:
            value = normalized_map.get(ExecutionSimpleExplanationService._normalize_key(raw_key))
            text = str(value or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _has_any_key(payload: dict[str, Any], keys: Iterable[str]) -> bool:
        normalized_payload_keys = {
            ExecutionSimpleExplanationService._normalize_key(key)
            for key in payload.keys()
        }
        return any(
            ExecutionSimpleExplanationService._normalize_key(candidate) in normalized_payload_keys
            for candidate in keys
        )

    @staticmethod
    def _normalize_key(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        normalized = unicodedata.normalize("NFKD", raw)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")

    @staticmethod
    def _is_insufficient_description(value: str) -> bool:
        normalized = str(value or "").strip()
        if not normalized:
            return True
        if len(normalized) < 8:
            return True
        return len([token for token in normalized.split() if token.strip()]) < 2

    @staticmethod
    def _has_clear_procedural_command(value: str) -> bool:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return False
        vague_tokens = {
            "nao identificado",
            "não identificado",
            "indefinido",
            "sem comando",
            "pendente",
            "n/a",
            "na",
        }
        return normalized not in vague_tokens

    @staticmethod
    def _has_identified_deadline(value: str) -> bool:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return False
        empty_tokens = {
            "sem prazo",
            "não identificado",
            "nao identificado",
            "indefinido",
            "n/a",
            "na",
        }
        return normalized not in empty_tokens

    @staticmethod
    def _has_meaningful_structured_output(result: dict[str, Any]) -> bool:
        for value in result.values():
            normalized = str(value or "").strip().lower()
            if normalized and normalized not in {
                "sem prazo",
                "não identificado",
                "nao identificado",
                "indefinido",
                "n/a",
                "na",
            }:
                return True
        return False

    @staticmethod
    def _clear_known_field(result: dict[str, Any], candidate_keys: Iterable[str]) -> None:
        normalized_keys = {
            ExecutionSimpleExplanationService._normalize_key(key): key
            for key in list(result.keys())
        }
        for candidate in candidate_keys:
            key = normalized_keys.get(ExecutionSimpleExplanationService._normalize_key(candidate))
            if key is not None:
                result[key] = ""

    @staticmethod
    def _apply_pending_ctr_fallback(result: dict[str, Any]) -> None:
        candidate_targets = (
            "reclassificacao",
            "classificacao",
            "classificacao_da_planilha",
            "categoria",
            "resultado",
        )
        normalized_keys = {
            ExecutionSimpleExplanationService._normalize_key(key): key
            for key in list(result.keys())
        }
        for candidate in candidate_targets:
            key = normalized_keys.get(ExecutionSimpleExplanationService._normalize_key(candidate))
            if key is not None:
                result[key] = PENDING_CTR_LABEL
                return

    def _build_row_explanation(
        self,
        *,
        result: dict[str, Any],
        issue_messages: list[str],
        errors: list[str],
    ) -> str:
        if errors:
            return "A linha ficou pendente porque a resposta retornou em formato incompatível com a estrutura esperada."
        if issue_messages:
            return issue_messages[0]
        classification = self._extract_first_value(
            result,
            ("reclassificacao", "classificacao", "classificacao_da_planilha", "categoria", "resultado"),
        )
        if classification and classification.strip().lower() == PENDING_CTR_LABEL.lower():
            return "A linha ficou como análise pendente porque não havia informação suficiente para um enquadramento seguro."
        return ""

    @staticmethod
    def _data_looks_empty(data_analyzed: Any) -> bool:
        if data_analyzed is None:
            return True
        if isinstance(data_analyzed, str):
            return not bool(data_analyzed.strip())
        if isinstance(data_analyzed, (list, tuple, set, dict)):
            return len(data_analyzed) == 0
        return False

    def _result_looks_pending(self, final_result: Any) -> bool:
        haystack = str(final_result or "").lower()
        return "pendente" in haystack or PENDING_CTR_LABEL.lower() in haystack

    @staticmethod
    def _mentions_incompleteness(value: str) -> bool:
        normalized = str(value or "").lower()
        return any(token in normalized for token in ("insuficiente", "incomplet", "vazi", "ambígu", "ambigu"))
