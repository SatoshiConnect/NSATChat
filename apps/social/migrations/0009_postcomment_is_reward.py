from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("social", "0008_postcomment_sticker_asset_alter_postcomment_text"),
    ]

    operations = [
        migrations.AddField(
            model_name="postcomment",
            name="is_reward",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
