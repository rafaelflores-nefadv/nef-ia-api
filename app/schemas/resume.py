from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DadosPessoais(BaseModel):
    nome: str | None = None
    email: str | None = None
    telefone: str | None = None
    cidade: str | None = None
    estado: str | None = None
    linkedin: str | None = None
    github: str | None = None


class Experiencia(BaseModel):
    cargo: str | None = None
    empresa: str | None = None
    periodo: str | None = None
    descricao: str | None = None


class Formacao(BaseModel):
    curso: str | None = None
    instituicao: str | None = None
    periodo: str | None = None
    nivel: str | None = None


class Idioma(BaseModel):
    nome: str | None = None
    nivel: str | None = None


class ResumeParseRequest(_StrictRequestModel):
    texto: str | None = None


class ResumeParseResponse(BaseModel):
    dados_pessoais: DadosPessoais
    objetivo: str | None = None
    resumo_profissional: str | None = None
    experiencias: list[Experiencia] = Field(default_factory=list)
    formacao: list[Formacao] = Field(default_factory=list)
    cursos: list[str] = Field(default_factory=list)
    habilidades: list[str] = Field(default_factory=list)
    idiomas: list[Idioma] = Field(default_factory=list)
    certificacoes: list[str] = Field(default_factory=list)
    texto_extraido: str
