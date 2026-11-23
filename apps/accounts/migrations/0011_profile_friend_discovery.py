from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_user_public_id")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="allow_id_search",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="allow_phone_search",
            field=models.BooleanField(default=True),
        ),
    ]
