from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("test_prompts", "0003_testpromptexecution"),
    ]

    operations = [
        migrations.AddField(
            model_name="testpromptexecution",
            name="remote_error_message",
            field=models.TextField(blank=True, default="", verbose_name="Erro remoto"),
        ),
        migrations.AddField(
            model_name="testpromptexecution",
            name="remote_execution_id",
            field=models.UUIDField(blank=True, db_index=True, null=True, verbose_name="ID remoto da execucao"),
        ),
        migrations.AddField(
            model_name="testpromptexecution",
            name="remote_last_checked_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Status remoto verificado em"),
        ),
        migrations.AddField(
            model_name="testpromptexecution",
            name="remote_phase",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="Fase remota"),
        ),
        migrations.AddField(
            model_name="testpromptexecution",
            name="remote_progress_percent",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Progresso remoto (%)"),
        ),
        migrations.AddField(
            model_name="testpromptexecution",
            name="remote_result_ready",
            field=models.BooleanField(default=False, verbose_name="Resultado remoto pronto"),
        ),
        migrations.AddField(
            model_name="testpromptexecution",
            name="remote_status",
            field=models.CharField(blank=True, default="", max_length=32, verbose_name="Status remoto"),
        ),
        migrations.AddField(
            model_name="testpromptexecution",
            name="remote_status_message",
            field=models.TextField(blank=True, default="", verbose_name="Mensagem de status remota"),
        ),
    ]
