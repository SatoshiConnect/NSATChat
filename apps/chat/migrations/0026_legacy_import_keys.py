from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0009_google_identity"),
        ("chat", "0025_message_status_ref"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatroom",
            name="legacy_id",
            field=models.CharField(blank=True, default=None, max_length=255, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="message",
            name="legacy_id",
            field=models.CharField(blank=True, default=None, max_length=255, null=True, unique=True),
        ),
    ]
