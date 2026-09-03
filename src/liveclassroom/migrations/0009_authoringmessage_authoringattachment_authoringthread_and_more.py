import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("liveclassroom", "0008_livesession_archived_at"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuthoringMessage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[("teacher", "Teacher"), ("assistant", "Assistant")],
                        max_length=16,
                    ),
                ),
                ("content", models.TextField()),
                ("model_identifier", models.CharField(blank=True, max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[("complete", "Complete"), ("failed", "Failed")],
                        default="complete",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "author",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="liveclassroom_authoring_messages",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.CreateModel(
            name="AuthoringAttachment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "source_type",
                    models.CharField(
                        choices=[
                            ("activity", "Activity"),
                            ("flow", "Flow"),
                            ("flow_item", "Flow item"),
                            ("provider", "Content provider"),
                        ],
                        max_length=32,
                    ),
                ),
                ("source_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("provider", models.CharField(blank=True, max_length=100)),
                ("reference", models.JSONField(blank=True, default=dict)),
                ("source_fingerprint", models.CharField(blank=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "message",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="liveclassroom.authoringmessage",
                    ),
                ),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="AuthoringThread",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "title",
                    models.CharField(default="New authoring conversation", max_length=200),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="liveclassroom_authoring_threads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.AddField(
            model_name="authoringmessage",
            name="thread",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="messages",
                to="liveclassroom.authoringthread",
            ),
        ),
        migrations.CreateModel(
            name="AuthoringJob",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("backend_key", models.CharField(max_length=100)),
                ("model_identifier", models.CharField(max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                        ],
                        default="queued",
                        max_length=16,
                    ),
                ),
                ("error_code", models.CharField(blank=True, max_length=64)),
                ("attempt", models.PositiveSmallIntegerField(default=1)),
                ("queued_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "assistant_message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="authoring_jobs_as_response",
                        to="liveclassroom.authoringmessage",
                    ),
                ),
                (
                    "message",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="jobs",
                        to="liveclassroom.authoringmessage",
                    ),
                ),
                (
                    "thread",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="jobs",
                        to="liveclassroom.authoringthread",
                    ),
                ),
            ],
            options={"ordering": ["-queued_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="authoringthread",
            index=models.Index(fields=["owner", "updated_at"], name="liveclassro_owner_i_f7d772_idx"),
        ),
        migrations.AddIndex(
            model_name="authoringjob",
            index=models.Index(fields=["thread", "status"], name="liveclassro_thread__1859db_idx"),
        ),
    ]
