from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("social", "0012_livestreamevent_sticker_asset")]

    operations = [
        migrations.AlterField(
            model_name="livestream",
            name="viewer_limit",
            field=models.PositiveSmallIntegerField(default=1000),
        ),
    ]
