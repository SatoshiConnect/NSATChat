from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_google_contact_sync"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="contact_phone",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
