from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_mhtalk_default_about")]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="phone_number",
            field=models.CharField(
                blank=True,
                help_text="Phone number in E.164 format (e.g. +923130067082)",
                max_length=20,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="google_sub",
            field=models.CharField(blank=True, default=None, max_length=255, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="user",
            name="legacy_id",
            field=models.CharField(blank=True, default=None, max_length=255, null=True, unique=True),
        ),
    ]
