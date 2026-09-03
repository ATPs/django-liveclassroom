from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("liveclassroom", "0005_liveactivity_reviewable")]

    operations = [
        migrations.AddField(
            model_name="commandreceipt",
            name="request_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
