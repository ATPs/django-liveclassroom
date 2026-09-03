from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("liveclassroom", "0006_commandreceipt_request_hash"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuthoringCommandReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("idempotency_key", models.CharField(max_length=160)),
                ("command_type", models.CharField(max_length=80)),
                ("request_hash", models.CharField(blank=True, default="", max_length=64)),
                ("response", models.JSONField(default=dict)),
                ("status_code", models.PositiveSmallIntegerField(default=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="liveclassroom_authoring_command_receipts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["owner", "created_at", "id"]},
        ),
        migrations.AddConstraint(
            model_name="authoringcommandreceipt",
            constraint=models.UniqueConstraint(
                fields=("owner", "idempotency_key"),
                name="lc_authoring_receipt_once",
            ),
        ),
    ]
