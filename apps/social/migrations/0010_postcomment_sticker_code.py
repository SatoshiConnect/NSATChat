from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("social", "0009_postcomment_is_reward")]

    operations = [migrations.AddField(
        model_name="postcomment",
        name="sticker_code",
        field=models.CharField(blank=True, default="", max_length=24),
    )]
