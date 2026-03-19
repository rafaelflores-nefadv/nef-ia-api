from django.db import models

from providers.models import Provider


class ProviderModel(models.Model):
    provider = models.ForeignKey(
        Provider,
        on_delete=models.PROTECT,
        related_name="provider_models",
        verbose_name="Provider",
    )
    fastapi_model_id = models.UUIDField(
        "ID do modelo na FastAPI",
        null=True,
        blank=True,
        unique=True,
    )
    name = models.CharField("Nome", max_length=150)
    slug = models.SlugField("Slug", max_length=160)
    description = models.TextField("Descricao", blank=True)
    context_window = models.PositiveIntegerField(
        "Janela de contexto",
        blank=True,
        null=True,
    )
    input_cost_per_1k = models.DecimalField(
        "Custo input por 1k",
        max_digits=12,
        decimal_places=6,
        default=0,
    )
    output_cost_per_1k = models.DecimalField(
        "Custo output por 1k",
        max_digits=12,
        decimal_places=6,
        default=0,
    )
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        ordering = ["provider__name", "name"]
        verbose_name = "Modelo"
        verbose_name_plural = "Modelos"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "slug"],
                name="uq_provider_model_provider_slug",
            )
        ]

    def __str__(self) -> str:
        return f"{self.provider.name} - {self.name}"
