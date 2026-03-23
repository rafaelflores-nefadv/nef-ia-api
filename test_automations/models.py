from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from .output_contract import has_explicit_contract, summarize_output_schema


class TestAutomation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("Nome", max_length=180)
    slug = models.SlugField("Slug", max_length=220, unique=True)
    provider_id = models.UUIDField("ID do provider na FastAPI")
    model_id = models.UUIDField("ID do modelo na FastAPI")
    credential_id = models.UUIDField("ID da credencial na FastAPI", null=True, blank=True)
    provider_slug = models.SlugField("Slug do provider", max_length=120)
    model_slug = models.SlugField("Slug do modelo", max_length=160)
    credential_name = models.CharField("Nome da credencial", max_length=120, blank=True, default="")
    output_type = models.CharField("Tipo de saida", max_length=64, blank=True, default="")
    result_parser = models.CharField("Parser de resultado", max_length=64, blank=True, default="")
    result_formatter = models.CharField("Formatador de resultado", max_length=64, blank=True, default="")
    output_schema = models.JSONField("Schema de saida", null=True, blank=True)
    debug_enabled = models.BooleanField("Modo debug da automacao", default=False)
    is_active = models.BooleanField("Ativa", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="test_automations_created",
        verbose_name="Criada por",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="test_automations_updated",
        verbose_name="Atualizada por",
    )
    created_at = models.DateTimeField("Criada em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizada em", auto_now=True)

    class Meta:
        ordering = ["-updated_at", "name"]
        verbose_name = "Automacao de teste"
        verbose_name_plural = "Automações de teste"

    def __str__(self) -> str:
        return self.name

    @property
    def has_explicit_output_contract(self) -> bool:
        return has_explicit_contract(
            output_type=self.output_type,
            result_parser=self.result_parser,
            result_formatter=self.result_formatter,
            output_schema=self.output_schema,
        )

    @property
    def output_schema_summary(self) -> str:
        return summarize_output_schema(self.output_schema)
