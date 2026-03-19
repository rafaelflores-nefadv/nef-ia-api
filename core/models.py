from django.db import models


class FastAPIIntegrationConfig(models.Model):
    base_url = models.URLField("Base URL FastAPI", max_length=500)
    is_active = models.BooleanField("Ativo", default=True)
    selected_integration_token = models.ForeignKey(
        "FastAPIIntegrationToken",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Token selecionado",
    )
    last_validated_at = models.DateTimeField("Ultima validacao em", null=True, blank=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Configuracao FastAPI"
        verbose_name_plural = "Configuracoes FastAPI"

    def __str__(self) -> str:
        return f"Integracao FastAPI ({'ativa' if self.is_active else 'inativa'})"


class FastAPIIntegrationToken(models.Model):
    config = models.ForeignKey(
        FastAPIIntegrationConfig,
        on_delete=models.CASCADE,
        related_name="integration_tokens",
        verbose_name="Configuracao",
    )
    name = models.CharField("Nome", max_length=120)
    integration_token = models.TextField("Token de integracao")
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Token de Integracao FastAPI"
        verbose_name_plural = "Tokens de Integracao FastAPI"
        ordering = ["-updated_at", "-id"]

    @property
    def masked_token(self) -> str:
        token = str(self.integration_token or "").strip()
        if not token:
            return "-"
        if len(token) <= 8:
            return "*" * len(token)
        return f"{token[:4]}...{token[-4:]}"

    def __str__(self) -> str:
        return self.name
