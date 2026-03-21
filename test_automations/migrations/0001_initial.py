from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TestAutomation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=180, verbose_name="Nome")),
                ("slug", models.SlugField(max_length=220, unique=True, verbose_name="Slug")),
                ("provider_id", models.UUIDField(verbose_name="ID do provider na FastAPI")),
                ("model_id", models.UUIDField(verbose_name="ID do modelo na FastAPI")),
                ("credential_id", models.UUIDField(blank=True, null=True, verbose_name="ID da credencial na FastAPI")),
                ("provider_slug", models.SlugField(max_length=120, verbose_name="Slug do provider")),
                ("model_slug", models.SlugField(max_length=160, verbose_name="Slug do modelo")),
                ("credential_name", models.CharField(blank=True, default="", max_length=120, verbose_name="Nome da credencial")),
                ("is_active", models.BooleanField(default=True, verbose_name="Ativa")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criada em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Atualizada em")),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="test_automations_created",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Criada por",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="test_automations_updated",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Atualizada por",
                    ),
                ),
            ],
            options={
                "verbose_name": "Automacao de teste",
                "verbose_name_plural": "Automações de teste",
                "ordering": ["-updated_at", "name"],
            },
        ),
    ]
