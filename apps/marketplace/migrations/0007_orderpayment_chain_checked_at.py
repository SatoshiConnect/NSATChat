"""Remember when reconciliation last re-read a confirmed transfer.

The reorg re-check used to read only the newest confirmed payments, so once a
week produced more than its page size the older transfers were never looked at
again. The cursor lets each pass continue from the least recently verified rows.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("marketplace", "0006_reconciliation_reports"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderpayment",
            name="chain_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
