from django.db import models

from providers.models import Provider


class ProviderCredential(models.Model):
    provider = models.ForeignKey(
        Provider,
        on_delete=models.PROTECT,
        related_name="credentials",
        verbose_name="Provider",
    )
    name = models.CharField("Nome", max_length=150)
    fastapi_credential_id = models.UUIDField(
        "ID da credencial na FastAPI",
        null=True,
        blank=True,
        unique=True,
    )
    api_key = models.TextField("API key")
    config_json = models.JSONField("Configuracao JSON", default=dict, blank=True)
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        ordering = ["provider__name", "name"]
        verbose_name = "Credencial"
        verbose_name_plural = "Credenciais"

    def __str__(self) -> str:
        return f"{self.provider.name} - {self.name}"

    @property
    def masked_api_key(self) -> str:
        value = (self.api_key or "").strip()
        if not value:
            return "********"

        if len(value) <= 6:
            return "********"

        return f"{value[:3]}****{value[-4:]}"
