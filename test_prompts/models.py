import uuid

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


class TestPromptExecution(models.Model):
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_COMPLETED, "Concluida"),
        (STATUS_FAILED, "Falhou"),
    )

    RESULT_TEXT = "text"
    RESULT_FILE = "file"
    RESULT_CHOICES = (
        (RESULT_TEXT, "Texto"),
        (RESULT_FILE, "Arquivo"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    test_prompt = models.ForeignKey(
        "test_prompts.TestPrompt",
        on_delete=models.CASCADE,
        related_name="executions",
        verbose_name="Prompt de teste",
    )
    test_automation_id = models.UUIDField("ID da automacao de teste")
    test_automation_name = models.CharField("Nome da automacao de teste", max_length=180)
    provider_id = models.UUIDField("ID do provider na FastAPI")
    model_id = models.UUIDField("ID do modelo na FastAPI")
    credential_id = models.UUIDField("ID da credencial na FastAPI", null=True, blank=True)
    provider_slug = models.SlugField("Slug do provider", max_length=120)
    model_slug = models.SlugField("Slug do modelo", max_length=160)
    credential_name = models.CharField("Nome da credencial", max_length=120, blank=True, default="")
    prompt_override = models.TextField("Prompt override aplicado")
    request_file_name = models.CharField("Nome do arquivo de entrada", max_length=255)
    request_file_mime_type = models.CharField("MIME type do arquivo de entrada", max_length=160, blank=True, default="")
    request_file_size = models.PositiveIntegerField("Tamanho do arquivo de entrada", default=0)
    status = models.CharField("Status", max_length=20, choices=STATUS_CHOICES)
    result_type = models.CharField("Tipo de resultado", max_length=20, choices=RESULT_CHOICES)
    output_text = models.TextField("Saida textual", blank=True, default="")
    output_file_name = models.CharField("Nome do arquivo de saida", max_length=255, blank=True, default="")
    output_file_mime_type = models.CharField("MIME type do arquivo de saida", max_length=160, blank=True, default="")
    output_file_size = models.PositiveIntegerField("Tamanho do arquivo de saida", default=0)
    output_file_content = models.BinaryField("Conteudo binario do arquivo de saida", null=True, blank=True)
    output_file_checksum = models.CharField("Checksum do arquivo de saida", max_length=128, blank=True, default="")
    provider_calls = models.PositiveIntegerField("Chamadas ao provider", default=0)
    input_tokens = models.PositiveIntegerField("Tokens de entrada", default=0)
    output_tokens = models.PositiveIntegerField("Tokens de saida", default=0)
    estimated_cost = models.DecimalField("Custo estimado", max_digits=18, decimal_places=6, default=0)
    duration_ms = models.PositiveIntegerField("Duracao em ms", default=0)
    error_message = models.TextField("Mensagem de erro", blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="test_prompt_executions_created",
        verbose_name="Criada por",
    )
    created_at = models.DateTimeField("Criada em", auto_now_add=True)
    finished_at = models.DateTimeField("Finalizada em", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Execucao de prompt de teste"
        verbose_name_plural = "Execucoes de prompts de teste"

    def __str__(self) -> str:
        return f"{self.test_prompt.name} - {self.id}"
