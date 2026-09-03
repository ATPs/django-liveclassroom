from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("liveclassroom", "0007_authoringcommandreceipt")]

    operations = [
        migrations.AddField(
            model_name="livesession",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
