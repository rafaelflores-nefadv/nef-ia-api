from django.db import models

from models_catalog.models import ProviderModel


class AIPrompt(models.Model):
    title = models.CharField("Titulo", max_length=120)
    content = models.TextField("Conteudo")
    ai_model = models.ForeignKey(
        ProviderModel,
        on_delete=models.PROTECT,
        related_name="ai_prompts",
        verbose_name="Modelo de IA",
    )
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        ordering = ["-updated_at", "title"]
        verbose_name = "Prompt"
        verbose_name_plural = "Prompts"

    def __str__(self) -> str:
        return self.title
