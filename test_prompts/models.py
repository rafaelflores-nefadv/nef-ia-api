from django.conf import settings
from django.db import models


class TestPrompt(models.Model):
    """
    Prompt experimental LOCAL (Django).

    Nao e fonte oficial de verdade e nao substitui o prompt remoto da automacao.
    """

    name = models.CharField("Nome", max_length=160)
    automation_id = models.UUIDField("ID da automacao de teste selecionada", db_index=True, null=True, blank=True)
    prompt_text = models.TextField("Texto do prompt experimental")
    notes = models.TextField("Observacoes", blank=True, default="")
    is_active = models.BooleanField("Ativo", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="test_prompts_created",
        verbose_name="Criado por",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="test_prompts_updated",
        verbose_name="Atualizado por",
    )
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        ordering = ["-updated_at", "name"]
        verbose_name = "Prompt de teste"
        verbose_name_plural = "Prompts de teste"

    def __str__(self) -> str:
        return self.name
