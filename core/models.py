from django.db import models


class FastAPIIntegrationConfig(models.Model):
    base_url = models.URLField("Base URL FastAPI", max_length=500)
    integration_token = models.TextField("Token de integracao", blank=True)
    token_name = models.CharField("Nome do token", max_length=120, blank=True)
    is_active = models.BooleanField("Ativo", default=True)
    last_validated_at = models.DateTimeField("Ultima validacao em", null=True, blank=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Configuracao FastAPI"
        verbose_name_plural = "Configuracoes FastAPI"

    def __str__(self) -> str:
        return f"Integracao FastAPI ({'ativa' if self.is_active else 'inativa'})"
