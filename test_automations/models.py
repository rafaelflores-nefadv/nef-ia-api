from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


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
