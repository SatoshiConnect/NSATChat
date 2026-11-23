import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("marketplace", "0002_creator_profiles_disputes")]

    operations = [
        migrations.CreateModel(
            name="DigitalItemAsset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="marketplace/assets/")),
                ("position", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assets", to="marketplace.digitalitem")),
            ],
            options={"ordering": ("position", "id")},
        ),
        migrations.AddConstraint(
            model_name="digitalitemasset",
            constraint=models.UniqueConstraint(fields=("item", "position"), name="marketplace_asset_item_position"),
        ),
    ]
