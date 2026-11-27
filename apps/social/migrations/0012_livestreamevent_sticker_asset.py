from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0008_giftevent_order_marketplaceorder_gift_recipient_and_more"),
        ("social", "0011_live_streams"),
    ]

    operations = [
        migrations.AddField(
            model_name="livestreamevent",
            name="sticker_asset",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="live_stream_events",
                to="marketplace.digitalitemasset",
            ),
        ),
    ]
