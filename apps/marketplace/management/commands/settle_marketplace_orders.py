"""Reconcile open NSAT marketplace orders with the indexer.

Checkout normally settles while the buyer watches, but a buyer closing the tab
must not leave a paid order unfulfilled. Run this from cron (every minute or
two) so submitted transfers still confirm, entitlements are granted, and
abandoned orders expire.
"""

from django.core.management.base import BaseCommand

from apps.marketplace import services
from apps.marketplace.models import MarketplaceOrder, OrderPayment


class Command(BaseCommand):
    help = "Confirm submitted marketplace payments and expire abandoned orders."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200, help="Maximum orders to reconcile per run.")

    def handle(self, *args, **options):
        limit = max(1, min(int(options["limit"]), 1000))
        pending = (
            MarketplaceOrder.objects.filter(
                state__in=[MarketplaceOrder.State.AWAITING_PAYMENT, MarketplaceOrder.State.PARTIALLY_PAID],
                payments__state=OrderPayment.State.PENDING,
                payments__tx_hash__gt="",
            )
            .distinct()
            .only("pk")[:limit]
        )
        confirmed = 0
        for order in pending:
            before = order.state
            try:
                settled = services.sync_order(order)
            except Exception as error:  # one bad order must not stop the run
                self.stderr.write(f"order {order.pk}: {error}")
                continue
            if settled.state == MarketplaceOrder.State.PAID and before != MarketplaceOrder.State.PAID:
                confirmed += 1
        expired = services.expire_open_orders(limit=limit)
        self.stdout.write(self.style.SUCCESS(
            f"Reconciled {len(pending)} submitted order(s): {confirmed} fulfilled, {expired} expired."
        ))
