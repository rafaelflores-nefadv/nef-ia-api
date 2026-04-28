from __future__ import annotations

import re
import unicodedata

from app.core.exceptions import AppException
from app.schemas.resume import DadosPessoais, Experiencia, Formacao, Idioma, ResumeParseResponse

EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b")
PHONE_RE = re.compile(r"(?:(?:\+?55)\s*)?(?:\(?\d{2}\)?\s*)?(?:9?\d{4})[-\s]?\d{4}\b")
URL_RE = re.compile(r"(?i)\b(?:https?://)?(?:www\.)?[^\s]+")
CITY_STATE_RE = re.compile(r"\b([A-Z][A-Za-z' ]+)\s*/\s*([A-Z]{2})\b")


class ResumeParserService:
    section_aliases = {
        "objetivo": {"objetivo"},
        "resumo_profissional": {"resumo profissional", "resumo", "perfil profissional", "sobre mim"},
        "experiencias": {"experiencia", "experiencias", "experiencia profissional", "experiencias profissionais"},
        "formacao": {"formacao", "formacao academica", "educacao", "escolaridade"},
        "habilidades": {"habilidades", "competencias", "stack", "tecnologias", "skills"},
        "idiomas": {"idiomas", "linguas", "languages"},
        "certificacoes": {"certificacoes", "certificados"},
        "cursos": {"cursos", "cursos complementares"},
    }

    skill_keywords = {
        "python",
        "java",
        "javascript",
        "typescript",
        "sql",
        "postgresql",
        "mysql",
        "django",
        "fastapi",
        "flask",
        "react",
        "node",
        "docker",
        "kubernetes",
        "aws",
        "azure",
        "gcp",
        "git",
        "github",
        "linux",
        "pandas",
        "excel",
        "power bi",
        "scrum",
        "agile",
        "rest",
        "api",
    }

    language_keywords = {
        "portugues",
        "ingles",
        "espanhol",
        "frances",
        "alemao",
        "italiano",
    }

    language_levels = {
        "basico",
        "intermediario",
        "avancado",
        "fluente",
        "nativo",
    }

    education_keywords = {
        "graduacao",
        "bacharelado",
        "tecnologo",
        "tecnico",
        "licenciatura",
        "mba",
        "pos-graduacao",
        "mestrado",
        "doutorado",
    }

    def parse(self, raw_text: str) -> ResumeParseResponse:
        text = self._normalize_text(raw_text)
        if not text:
            raise AppException(
                "Resume text is required.",
                status_code=422,
                code="empty_resume_text",
            )

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        sections = self._split_sections(lines)

        dados_pessoais = DadosPessoais(
            nome=self._extract_name(lines),
            email=self._extract_email(text),
            telefone=self._extract_phone(text),
            cidade=self._extract_city(text),
            estado=self._extract_state(text),
            linkedin=self._extract_profile_url(text, "linkedin.com"),
            github=self._extract_profile_url(text, "github.com"),
        )

        return ResumeParseResponse(
            dados_pessoais=dados_pessoais,
            objetivo=self._extract_single_section(sections, "objetivo"),
            resumo_profissional=self._extract_single_section(sections, "resumo_profissional"),
            experiencias=self._extract_experiences(sections),
            formacao=self._extract_education(sections),
            cursos=self._extract_simple_items(sections, "cursos"),
            habilidades=self._extract_skills(sections, text),
            idiomas=self._extract_languages(sections, text),
            certificacoes=self._extract_simple_items(sections, "certificacoes"),
            texto_extraido=text,
        )

    def _normalize_text(self, raw_text: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(raw_text or ""))
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    def _normalize_token(self, value: str) -> str:
        ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        ascii_value = ascii_value.lower().strip()
        ascii_value = re.sub(r"[^a-z0-9\s]", " ", ascii_value)
        return re.sub(r"\s+", " ", ascii_value).strip()

    def _split_sections(self, lines: list[str]) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {}
        current_key: str | None = None

        for line in lines:
            normalized_line = self._normalize_token(line.rstrip(":"))
            section_key = self._resolve_section_key(normalized_line)
            if section_key is not None:
                current_key = section_key
                sections.setdefault(current_key, [])
                continue
            if current_key is not None:
                sections.setdefault(current_key, []).append(line)
        return sections

    def _resolve_section_key(self, normalized_line: str) -> str | None:
        for key, aliases in self.section_aliases.items():
            if normalized_line in aliases:
                return key
        return None

    def _extract_name(self, lines: list[str]) -> str | None:
        for line in lines[:6]:
            if self._looks_like_heading(line):
                continue
            if EMAIL_RE.search(line):
                continue
            candidate = re.sub(r"[^A-Za-z' ]", " ", line).strip()
            words = [word for word in candidate.split() if word]
            if 2 <= len(words) <= 5 and all(len(word) > 1 for word in words):
                return " ".join(word.capitalize() if word.islower() else word for word in words)
        return None

    def _extract_email(self, text: str) -> str | None:
        match = EMAIL_RE.search(text)
        return match.group(0) if match else None

    def _extract_phone(self, text: str) -> str | None:
        match = PHONE_RE.search(text)
        if not match:
            return None
        return self._normalize_phone(match.group(0))

    def _extract_city(self, text: str) -> str | None:
        match = CITY_STATE_RE.search(text)
        if not match:
            return None
        return match.group(1).strip()

    def _extract_state(self, text: str) -> str | None:
        match = CITY_STATE_RE.search(text)
        if not match:
            return None
        return match.group(2).strip().upper()

    def _extract_profile_url(self, text: str, domain: str) -> str | None:
        for match in URL_RE.finditer(text):
            value = match.group(0).rstrip(".,);")
            lowered = value.lower()
            if domain not in lowered:
                continue
            if not lowered.startswith(("http://", "https://")):
                value = f"https://{value}"
            return value
        return None

    def _extract_single_section(self, sections: dict[str, list[str]], key: str) -> str | None:
        values = [line.strip("- ").strip() for line in sections.get(key, []) if line.strip()]
        if not values:
            return None
        return " ".join(values).strip() or None

    def _extract_experiences(self, sections: dict[str, list[str]]) -> list[Experiencia]:
        lines = sections.get("experiencias", [])
        return [
            Experiencia(
                cargo=item,
                empresa=None,
                periodo=self._extract_period(item),
                descricao=None,
            )
            for item in self._group_bullets(lines)
        ]

    def _extract_education(self, sections: dict[str, list[str]]) -> list[Formacao]:
        items: list[Formacao] = []
        for item in self._group_bullets(sections.get("formacao", [])):
            normalized = self._normalize_token(item)
            level = None
            for keyword in self.education_keywords:
                if keyword in normalized:
                    level = keyword
                    break
            items.append(
                Formacao(
                    curso=item,
                    instituicao=None,
                    periodo=self._extract_period(item),
                    nivel=level,
                )
            )
        return items

    def _extract_simple_items(self, sections: dict[str, list[str]], key: str) -> list[str]:
        return self._dedupe_preserve_order(
            [item for item in self._group_bullets(sections.get(key, [])) if item]
        )

    def _extract_skills(self, sections: dict[str, list[str]], text: str) -> list[str]:
        items = self._group_bullets(sections.get("habilidades", []))
        if items:
            expanded: list[str] = []
            for item in items:
                expanded.extend(self._split_inline_list(item))
            return self._dedupe_preserve_order(expanded)

        lowered = self._normalize_token(text)
        found = [skill.title() if skill != "aws" else "AWS" for skill in self.skill_keywords if skill in lowered]
        return self._dedupe_preserve_order(found)

    def _extract_languages(self, sections: dict[str, list[str]], text: str) -> list[Idioma]:
        source_items = self._group_bullets(sections.get("idiomas", []))
        if not source_items:
            source_items = self._infer_languages_from_text(text)

        languages: list[Idioma] = []
        for item in source_items:
            normalized = self._normalize_token(item)
            language_name = None
            for keyword in self.language_keywords:
                if keyword in normalized:
                    language_name = keyword.capitalize()
                    break
            if language_name is None:
                continue
            level = None
            for candidate_level in self.language_levels:
                if candidate_level in normalized:
                    level = candidate_level.capitalize()
                    break
            languages.append(Idioma(nome=language_name, nivel=level))
        return languages

    def _infer_languages_from_text(self, text: str) -> list[str]:
        normalized = self._normalize_token(text)
        found: list[str] = []
        for keyword in self.language_keywords:
            if keyword in normalized:
                found.append(keyword.capitalize())
        return found

    def _group_bullets(self, lines: list[str]) -> list[str]:
        items: list[str] = []
        current: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            is_bullet = stripped.startswith(("-", "*", "\u2022")) or bool(re.match(r"^\d+[\.\)]\s+", stripped))
            cleaned = re.sub(r"^(?:[-*\u2022]\s*|\d+[\.\)]\s*)", "", stripped).strip()
            if is_bullet and current:
                items.append(" ".join(current).strip())
                current = [cleaned]
            elif is_bullet:
                current = [cleaned]
            elif current:
                current.append(cleaned)
            else:
                items.append(cleaned)

        if current:
            items.append(" ".join(current).strip())

        flattened: list[str] = []
        for item in items:
            if "," in item and len(item) < 120:
                flattened.extend(self._split_inline_list(item))
            else:
                flattened.append(item)
        return self._dedupe_preserve_order([item for item in flattened if item])

    def _split_inline_list(self, item: str) -> list[str]:
        parts = [part.strip(" -") for part in re.split(r"[;,|]", item) if part.strip(" -")]
        return parts or ([item.strip()] if item.strip() else [])

    def _extract_period(self, text: str) -> str | None:
        match = re.search(r"\b\d{4}\s*[-/]\s*(?:\d{4}|atual|presente)\b", text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
        month_match = re.search(
            r"\b(?:jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*\/\d{4}\s*[-/]\s*(?:atual|presente|(?:jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*\/\d{4})\b",
            self._normalize_token(text),
            flags=re.IGNORECASE,
        )
        if month_match:
            return month_match.group(0)
        return None

    def _normalize_phone(self, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if digits.startswith("55") and len(digits) > 11:
            digits = digits[2:]
        if len(digits) == 11:
            return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
        if len(digits) == 10:
            return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
        return value.strip()

    def _looks_like_heading(self, line: str) -> bool:
        normalized = self._normalize_token(line.rstrip(":"))
        return self._resolve_section_key(normalized) is not None

    def _dedupe_preserve_order(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            normalized = self._normalize_token(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(item.strip())
        return result
