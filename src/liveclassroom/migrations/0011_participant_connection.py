from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("liveclassroom", "0010_canonical_flow_steps")]

    operations = [
        migrations.CreateModel(
            name="ParticipantConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("connection_id", models.CharField(max_length=255, unique=True)),
                ("connected_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("disconnected_at", models.DateTimeField(blank=True, null=True)),
                (
                    "participant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="connections",
                        to="liveclassroom.participant",
                    ),
                ),
            ],
            options={"ordering": ["participant", "connected_at"]},
        ),
        migrations.AddIndex(
            model_name="participantconnection",
            index=models.Index(fields=["participant", "disconnected_at"], name="liveclassro_partici_19bd82_idx"),
        ),
    ]
