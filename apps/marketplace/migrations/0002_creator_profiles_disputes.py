import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("marketplace", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="PurchaseDispute",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(max_length=500)),
                ("state", models.CharField(choices=[("open", "Open"), ("reviewed", "Reviewed"), ("resolved", "Resolved"), ("dismissed", "Dismissed")], db_index=True, default="open", max_length=12)),
                ("simulation_only", models.BooleanField(default=True, editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("buyer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="marketplace_disputes", to=settings.AUTH_USER_MODEL)),
                ("purchase", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="dispute", to="marketplace.simulatedpurchase")),
            ],
        ),
        migrations.CreateModel(
            name="CreatorProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(blank=True, max_length=80)),
                ("bio", models.CharField(blank=True, max_length=500)),
                ("is_public", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="creator_profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
