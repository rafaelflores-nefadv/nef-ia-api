import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("test_prompts", "0002_alter_testprompt_automation_id_nullable"),
    ]

    operations = [
        migrations.CreateModel(
            name="TestPromptExecution",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("test_automation_id", models.UUIDField(verbose_name="ID da automacao de teste")),
                ("test_automation_name", models.CharField(max_length=180, verbose_name="Nome da automacao de teste")),
                ("provider_id", models.UUIDField(verbose_name="ID do provider na FastAPI")),
                ("model_id", models.UUIDField(verbose_name="ID do modelo na FastAPI")),
                ("credential_id", models.UUIDField(blank=True, null=True, verbose_name="ID da credencial na FastAPI")),
                ("provider_slug", models.SlugField(max_length=120, verbose_name="Slug do provider")),
                ("model_slug", models.SlugField(max_length=160, verbose_name="Slug do modelo")),
                ("credential_name", models.CharField(blank=True, default="", max_length=120, verbose_name="Nome da credencial")),
                ("prompt_override", models.TextField(verbose_name="Prompt override aplicado")),
                ("request_file_name", models.CharField(max_length=255, verbose_name="Nome do arquivo de entrada")),
                ("request_file_mime_type", models.CharField(blank=True, default="", max_length=160, verbose_name="MIME type do arquivo de entrada")),
                ("request_file_size", models.PositiveIntegerField(default=0, verbose_name="Tamanho do arquivo de entrada")),
                ("status", models.CharField(choices=[("completed", "Concluida"), ("failed", "Falhou")], max_length=20, verbose_name="Status")),
                ("result_type", models.CharField(choices=[("text", "Texto"), ("file", "Arquivo")], max_length=20, verbose_name="Tipo de resultado")),
                ("output_text", models.TextField(blank=True, default="", verbose_name="Saida textual")),
                ("output_file_name", models.CharField(blank=True, default="", max_length=255, verbose_name="Nome do arquivo de saida")),
                ("output_file_mime_type", models.CharField(blank=True, default="", max_length=160, verbose_name="MIME type do arquivo de saida")),
                ("output_file_size", models.PositiveIntegerField(default=0, verbose_name="Tamanho do arquivo de saida")),
                ("output_file_content", models.BinaryField(blank=True, null=True, verbose_name="Conteudo binario do arquivo de saida")),
                ("output_file_checksum", models.CharField(blank=True, default="", max_length=128, verbose_name="Checksum do arquivo de saida")),
                ("provider_calls", models.PositiveIntegerField(default=0, verbose_name="Chamadas ao provider")),
                ("input_tokens", models.PositiveIntegerField(default=0, verbose_name="Tokens de entrada")),
                ("output_tokens", models.PositiveIntegerField(default=0, verbose_name="Tokens de saida")),
                ("estimated_cost", models.DecimalField(decimal_places=6, default=0, max_digits=18, verbose_name="Custo estimado")),
                ("duration_ms", models.PositiveIntegerField(default=0, verbose_name="Duracao em ms")),
                ("error_message", models.TextField(blank=True, default="", verbose_name="Mensagem de erro")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criada em")),
                ("finished_at", models.DateTimeField(auto_now=True, verbose_name="Finalizada em")),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="test_prompt_executions_created",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Criada por",
                    ),
                ),
                (
                    "test_prompt",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="executions",
                        to="test_prompts.testprompt",
                        verbose_name="Prompt de teste",
                    ),
                ),
            ],
            options={
                "verbose_name": "Execucao de prompt de teste",
                "verbose_name_plural": "Execucoes de prompts de teste",
                "ordering": ["-created_at"],
            },
        ),
    ]
