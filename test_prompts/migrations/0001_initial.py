from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TestPrompt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160, verbose_name="Nome")),
                ("automation_id", models.UUIDField(db_index=True, verbose_name="ID da automacao oficial")),
                ("prompt_text", models.TextField(verbose_name="Texto do prompt experimental")),
                ("notes", models.TextField(blank=True, default="", verbose_name="Observacoes")),
                ("is_active", models.BooleanField(default=True, verbose_name="Ativo")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Atualizado em")),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="test_prompts_created",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Criado por",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="test_prompts_updated",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Atualizado por",
                    ),
                ),
            ],
            options={
                "verbose_name": "Prompt de teste",
                "verbose_name_plural": "Prompts de teste",
                "ordering": ["-updated_at", "name"],
            },
        ),
    ]

