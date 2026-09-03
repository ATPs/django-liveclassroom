from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("liveclassroom", "0004_alter_participant_user_and_more")]

    operations = [
        migrations.AddField(
            model_name="liveactivity",
            name="reviewable",
            field=models.BooleanField(default=False),
        ),
    ]
