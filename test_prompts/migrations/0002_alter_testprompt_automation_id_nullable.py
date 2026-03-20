from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("test_prompts", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="testprompt",
            name="automation_id",
            field=models.UUIDField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="ID da automacao tecnica (interna)",
            ),
        ),
    ]

