from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0011_profile_friend_discovery")]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="about",
            field=models.CharField(
                blank=True,
                default="Hey there! I'm using SatoshiCore.",
                help_text="User status or bio.",
                max_length=150,
            ),
        ),
    ]
