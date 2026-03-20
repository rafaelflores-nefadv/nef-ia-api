from django.db import models


class Provider(models.Model):
    """
    LEGADO (transicao): espelho tecnico local para compatibilidade administrativa.

    Nao usar este model como fonte da verdade para providers operacionais.
    A fonte oficial e a FastAPI/banco operacional remoto.
    """

    name = models.CharField("Nome", max_length=150)
    slug = models.SlugField("Slug", max_length=160, unique=True)
    # Marcador tecnico de vinculacao remota. Nao representa autoridade local.
    fastapi_provider_id = models.UUIDField(
        "ID do provider na FastAPI",
        null=True,
        blank=True,
        unique=True,
    )
    description = models.TextField("Descricao", blank=True)
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Provider"
        verbose_name_plural = "Providers"

    def __str__(self) -> str:
        return self.name
