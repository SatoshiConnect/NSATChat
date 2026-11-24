import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("marketplace", "0003_digitalitemasset"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketplaceOrder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("idempotency_key", models.UUIDField()),
                ("unit_amount_nsat", models.PositiveBigIntegerField()),
                ("platform_fee_bps", models.PositiveSmallIntegerField(default=0)),
                ("platform_fee_nsat", models.PositiveBigIntegerField(default=0)),
                ("creator_proceeds_nsat", models.PositiveBigIntegerField()),
                ("network", models.CharField(max_length=64)),
                ("treasury_address", models.CharField(blank=True, default="", max_length=56)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("awaiting_payment", "Awaiting payment"),
                            ("partially_paid", "Partially paid"),
                            ("paid", "Paid"),
                            ("expired", "Expired"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="awaiting_payment",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("expires_at", models.DateTimeField()),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                (
                    "buyer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="marketplace_orders",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="orders",
                        to="marketplace.digitalitem",
                    ),
                ),
            ],
            options={
                "db_table": "marketplace_orders",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="marketplaceorder",
            constraint=models.UniqueConstraint(fields=("buyer", "idempotency_key"), name="marketplace_order_idempotency"),
        ),
        migrations.AddIndex(
            model_name="marketplaceorder",
            index=models.Index(fields=["state", "expires_at"], name="mkt_order_state_exp"),
        ),
        migrations.CreateModel(
            name="OrderPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("creator", "Creator share"), ("platform", "Platform fee")], max_length=16)),
                ("payee_address", models.CharField(max_length=56)),
                ("amount_nsat", models.PositiveBigIntegerField()),
                ("tx_hash", models.CharField(blank=True, default="", max_length=64)),
                ("submitted_at", models.BigIntegerField(blank=True, null=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("ledger", models.BigIntegerField(blank=True, null=True)),
                (
                    "state",
                    models.CharField(
                        choices=[("pending", "Pending"), ("confirmed", "Confirmed"), ("failed", "Failed")],
                        db_index=True,
                        default="pending",
                        max_length=12,
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payments",
                        to="marketplace.marketplaceorder",
                    ),
                ),
            ],
            options={
                "db_table": "marketplace_order_payments",
                "ordering": ("role",),
            },
        ),
        migrations.AddConstraint(
            model_name="orderpayment",
            constraint=models.UniqueConstraint(fields=("order", "role"), name="marketplace_order_payment_role"),
        ),
        migrations.AddConstraint(
            model_name="orderpayment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("tx_hash", ""), _negated=True),
                fields=("tx_hash",),
                name="marketplace_order_payment_tx",
            ),
        ),
        migrations.CreateModel(
            name="MarketplaceEntitlement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("acquired_at", models.DateTimeField(auto_now_add=True)),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="entitlements",
                        to="marketplace.digitalitem",
                    ),
                ),
                (
                    "order",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entitlement",
                        to="marketplace.marketplaceorder",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="marketplace_entitlements",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "marketplace_entitlements",
                "ordering": ("-acquired_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="marketplaceentitlement",
            constraint=models.UniqueConstraint(fields=("owner", "item"), name="marketplace_entitlement_unique"),
        ),
        migrations.CreateModel(
            name="CreatorSale",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("gross_nsat", models.PositiveBigIntegerField()),
                ("platform_fee_nsat", models.PositiveBigIntegerField(default=0)),
                ("creator_proceeds_nsat", models.PositiveBigIntegerField()),
                ("tx_hash", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "creator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="marketplace_sales",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="creator_sales",
                        to="marketplace.digitalitem",
                    ),
                ),
                (
                    "order",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="creator_sale",
                        to="marketplace.marketplaceorder",
                    ),
                ),
            ],
            options={
                "db_table": "marketplace_creator_sales",
                "ordering": ("-created_at",),
            },
        ),
    ]
