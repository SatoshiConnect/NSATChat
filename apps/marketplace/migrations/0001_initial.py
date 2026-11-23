import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def seed_catalog(apps, schema_editor):
    DigitalItem = apps.get_model("marketplace", "DigitalItem")
    for kind, title, description, price in (
        ("gift", "Green Heart", "A friendly way to support a creator.", 10),
        ("gift", "Starburst", "A bright thank-you for a creator.", 25),
        ("sticker_pack", "SatoshiCore Basics", "Starter sticker pack preview.", 0),
        ("profile_frame", "Emerald Frame", "A profile frame for your collection.", 50),
        ("badge", "Early Supporter", "A digital profile badge.", 100),
        ("theme", "Forest Night", "A dark green interface theme.", 75),
        ("avatar", "Pixel Leaf", "A pixel avatar accessory.", 20),
        ("pixel_world", "Garden Tile", "A decorative Pixel World tile.", 30),
    ):
        DigitalItem.objects.get_or_create(
            creator=None,
            kind=kind,
            title=title,
            defaults={
                "description": description,
                "proposed_price_nsat": price,
                "usage_rights": "Personal in-app use; no transfer or resale.",
                "state": "approved",
            },
        )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0014_profile_contact_phone"),
        ("status", "0005_statusreaction"),
    ]

    operations = [
        migrations.CreateModel(
            name="DigitalItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("gift", "Creator gift"), ("sticker_pack", "Sticker pack"), ("profile_frame", "Profile frame"), ("badge", "Badge"), ("theme", "Theme"), ("avatar", "Avatar accessory"), ("pixel_world", "Pixel World item")], db_index=True, max_length=24)),
                ("title", models.CharField(max_length=100)),
                ("description", models.CharField(blank=True, max_length=1000)),
                ("preview", models.ImageField(blank=True, upload_to="marketplace/previews/")),
                ("proposed_price_nsat", models.PositiveBigIntegerField(default=0, help_text="Display-only proposed price; not charged.")),
                ("usage_rights", models.CharField(blank=True, max_length=500)),
                ("state", models.CharField(choices=[("draft", "Draft"), ("pending", "Pending review"), ("approved", "Approved"), ("rejected", "Rejected"), ("disabled", "Disabled")], db_index=True, default="pending", max_length=12)),
                ("moderation_note", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("creator", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="marketplace_items", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="SimulatedPurchase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("idempotency_key", models.UUIDField()),
                ("amount_nsat", models.PositiveBigIntegerField()),
                ("state", models.CharField(choices=[("pending", "Pending simulation"), ("confirmed", "Simulation confirmed"), ("failed", "Simulation failed")], default="confirmed", max_length=12)),
                ("simulation_only", models.BooleanField(default=True, editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("buyer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="marketplace_simulated_purchases", to=settings.AUTH_USER_MODEL)),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="simulated_purchases", to="marketplace.digitalitem")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="InventoryItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("acquired_at", models.DateTimeField(auto_now_add=True)),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="inventory_entries", to="marketplace.digitalitem")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="marketplace_inventory", to=settings.AUTH_USER_MODEL)),
                ("purchase", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="inventory_entry", to="marketplace.simulatedpurchase")),
            ],
        ),
        migrations.CreateModel(
            name="GiftEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("simulation_only", models.BooleanField(default=True, editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="gift_events", to="marketplace.digitalitem")),
                ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="marketplace_gifts_received", to=settings.AUTH_USER_MODEL)),
                ("sender", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="marketplace_gifts_sent", to=settings.AUTH_USER_MODEL)),
                ("status", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="creator_gifts", to="status.status")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="ItemReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(choices=[("copyright", "Copyright"), ("unsafe", "Unsafe"), ("spam", "Spam"), ("other", "Other")], max_length=32)),
                ("details", models.CharField(blank=True, max_length=1000)),
                ("state", models.CharField(choices=[("open", "Open"), ("reviewed", "Reviewed"), ("dismissed", "Dismissed"), ("actioned", "Actioned")], db_index=True, default="open", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reports", to="marketplace.digitalitem")),
                ("reporter", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="marketplace_reports", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="MarketplaceAuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(db_index=True, max_length=40)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="marketplace.digitalitem")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="CreatorNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(max_length=32)),
                ("message", models.CharField(max_length=200)),
                ("is_read", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="creator_actions", to=settings.AUTH_USER_MODEL)),
                ("item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="marketplace.digitalitem")),
                ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="creator_notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddConstraint(model_name="simulatedpurchase", constraint=models.UniqueConstraint(fields=("buyer", "idempotency_key"), name="marketplace_purchase_idempotency")),
        migrations.AddConstraint(model_name="inventoryitem", constraint=models.UniqueConstraint(fields=("owner", "item", "purchase"), name="marketplace_inventory_unique")),
        migrations.AddIndex(model_name="digitalitem", index=models.Index(fields=["state", "kind", "created_at"], name="mkt_state_kind_created")),
        migrations.RunPython(seed_catalog, migrations.RunPython.noop),
    ]
