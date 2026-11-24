"""Chain-versus-ledger reconciliation for NSAT marketplace settlement.

Checkout settles while the buyer watches and the settling command keeps submitted
transfers moving, but neither proofreads the books. This pass compares what the
indexer reports about the chain with what the ledger recorded and hands admins a
report they can act on.

It repairs only what cannot move money: an entitlement and sale record that are
missing for an order the chain already confirmed. Amounts, payment states and
confirmations are reported, never rewritten, because silently "fixing" a payment
row would hide exactly the disagreement admins must see.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from . import services
from .models import (
    CreatorSale,
    MarketplaceAuditEvent,
    MarketplaceEntitlement,
    MarketplaceOrder,
    MarketplaceReconciliationIssue,
    MarketplaceReconciliationRun,
    OrderPayment,
)

logger = logging.getLogger(__name__)

CRITICAL = MarketplaceReconciliationIssue.Severity.CRITICAL
WARNING = MarketplaceReconciliationIssue.Severity.WARNING
OPEN_STATES = (MarketplaceOrder.State.AWAITING_PAYMENT, MarketplaceOrder.State.PARTIALLY_PAID)
# A pass that has not finished in this long lost its process (deploy, OOM kill).
# Its run row is closed so the admin list never shows a pass that is not coming
# back, which would otherwise look like an audit that was still working.
RUN_STALE_MINUTES = 60


def _bounded_setting(name, default, low, high):
    try:
        value = int(getattr(settings, name))
    except (TypeError, ValueError):
        value = default
    return min(max(value, low), high)


def stale_minutes():
    """How long a submitted transfer may stay unconfirmed before it is reported."""
    return _bounded_setting("MARKETPLACE_RECONCILIATION_STALE_MINUTES", 30, 1, 60 * 24)


def recheck_days():
    """Re-verify confirmed payments from this many recent days; 0 disables it."""
    return _bounded_setting("MARKETPLACE_RECONCILIATION_RECHECK_DAYS", 7, 0, 90)


def _chain_verdict(payment):
    """Ask the indexer about one payment; ``None`` means the answer is unknown."""
    if not payment.tx_hash or not payment.submitted_at:
        return None
    try:
        return services.confirmation_for_hash(payment.tx_hash, payment.submitted_at)
    except services.GATEWAY_TRANSIENT_ERRORS:
        logger.warning("reconciliation could not read chain state for %s", payment.tx_hash, exc_info=True)
        return None


def _confirmed(verdict):
    return verdict is not None and verdict["status"] == "confirmed" and verdict["success"] is True


def _failed(verdict):
    if verdict is None:
        return False
    return verdict["status"] == "failed" or (verdict["status"] == "confirmed" and verdict["success"] is False)


def _age_minutes(payment):
    if not payment.submitted_at:
        return 0
    return max(0, int((timezone.now().timestamp() - payment.submitted_at) // 60))


class Report:
    """Collects what one pass scanned and found, then writes it to the run row."""

    def __init__(self, run):
        self.run = run
        self.order_ids = set()
        self.payment_ids = set()
        self.chain_checks = 0
        self.issues = 0
        self.critical = 0
        self.repairs = 0
        # Orders this pass could not settle; a later check must not report the
        # same stuck order a second time as a different finding.
        self.sync_failures = set()

    def scan_order(self, order_id):
        self.order_ids.add(order_id)

    def scan_payment(self, payment_id):
        self.payment_ids.add(payment_id)

    def chain_check(self):
        self.chain_checks += 1

    def issue(self, code, severity, *, order=None, payment=None, detail="", repaired=False):
        applied = bool(repaired and not self.run.dry_run)
        note = str(detail)[:300]
        if repaired and not applied:
            note = f"{note} (dry run: not applied)"[:300]
        MarketplaceReconciliationIssue.objects.create(
            run=self.run,
            code=code,
            severity=severity,
            order=order,
            order_reference=getattr(order, "pk", None),
            payment=payment,
            detail=note,
            repaired=applied,
        )
        self.issues += 1
        if severity == CRITICAL:
            self.critical += 1
        if applied:
            self.repairs += 1
        return applied


def _settle_submitted_payments(report, limit, check_chain):
    """Finish orders whose transfer the chain may already have confirmed."""
    payments = list(
        OrderPayment.objects.filter(state=OrderPayment.State.PENDING, tx_hash__gt="")
        .select_related("order")
        .order_by("submitted_at")[:limit]
    )
    orders = {}
    for payment in payments:
        report.scan_payment(payment.pk)
        report.scan_order(payment.order_id)
        if payment.order.state in OPEN_STATES:
            orders[payment.order_id] = payment.order

    for order in orders.values():
        pending = list(order.payments.filter(state=OrderPayment.State.PENDING, tx_hash__gt=""))
        if not check_chain:
            _report_stalled(report, order, pending)
            continue
        if report.run.dry_run:
            # A dry run may look at the chain but must not settle anything.
            for payment in pending:
                verdict = _chain_verdict(payment)
                if verdict is not None:
                    report.chain_check()
                if _confirmed(verdict):
                    report.issue(
                        "order_confirmed_but_open",
                        CRITICAL,
                        order=order,
                        payment=payment,
                        detail=f"The chain already confirms {payment.tx_hash[:16]}…; a real run would grant access.",
                    )
                elif _failed(verdict):
                    report.issue(
                        "payment_failed_on_chain",
                        WARNING,
                        order=order,
                        payment=payment,
                        detail=f"{payment.role} transfer failed on chain; the order stays open for review.",
                    )
            _report_stalled(report, order, pending)
            continue

        # sync_order reads the indexer once per submitted transfer.
        for _ in pending:
            report.chain_check()
        try:
            settled = services.sync_order(order, allow_terminal=False)
        except Exception as error:  # one bad order must not stop the audit
            logger.exception("reconciliation could not settle order %s", order.pk)
            report.sync_failures.add(order.pk)
            report.issue(
                "order_sync_failed",
                CRITICAL,
                order=order,
                detail=f"Settlement sync raised {type(error).__name__}; the next run retries it.",
            )
            continue
        if settled.state == MarketplaceOrder.State.PAID:
            report.issue(
                "order_settled_late",
                WARNING,
                order=settled,
                detail="The transfer confirmed after checkout; reconciliation granted the rights.",
                repaired=True,
            )
            continue
        if settled.state == MarketplaceOrder.State.FAILED:
            report.issue(
                "payment_failed_on_chain",
                WARNING,
                order=settled,
                detail="A required transfer failed on chain; the order was closed as failed.",
            )
            continue
        _report_stalled(report, settled, list(settled.payments.filter(state=OrderPayment.State.PENDING, tx_hash__gt="")))


def _report_stalled(report, order, pending):
    threshold = stale_minutes()
    for payment in pending:
        age = _age_minutes(payment)
        if age >= threshold:
            report.issue(
                "payment_stalled",
                WARNING,
                order=order,
                payment=payment,
                detail=f"{payment.role} transfer submitted {age} min ago is still unconfirmed (threshold {threshold}).",
            )


def _settlement_proven(payments, total):
    """Access may only be rebuilt for an order its confirmed transfers back.

    A paid row with a missing or disputed confirmation is exactly the
    disagreement an admin has to resolve; granting access from such a row would
    hand out paid content on the strength of a record nobody verified.
    """
    return bool(payments) and all(
        payment.state == OrderPayment.State.CONFIRMED for payment in payments
    ) and total == sum(payment.amount_nsat for payment in payments)


def _repair_settlement(report, order):
    """Recreate rights and sale records an already paid order is missing."""
    entitlement_missing = not MarketplaceEntitlement.objects.filter(order=order).exists()
    sale_missing = bool(order.item.creator_id) and not CreatorSale.objects.filter(order=order).exists()
    if not entitlement_missing and not sale_missing:
        return
    if report.run.dry_run:
        if entitlement_missing:
            report.issue("order_missing_entitlement", CRITICAL, order=order, detail="Paid order has no entitlement.", repaired=True)
        if sale_missing:
            report.issue("order_missing_sale", WARNING, order=order, detail="Paid order has no creator sale record.", repaired=True)
        return

    with transaction.atomic():
        locked = MarketplaceOrder.objects.select_for_update().select_related("item").get(pk=order.pk)
        entitlement_created, sale_created = services.ensure_settlement_records(locked)
        MarketplaceAuditEvent.objects.create(
            actor=None,
            item=locked.item,
            action="order.repaired",
            metadata={
                "order": str(locked.pk),
                "entitlement_created": entitlement_created,
                "sale_created": sale_created,
                "source": "reconciliation",
                "run": str(report.run.pk),
            },
        )
    if entitlement_missing:
        if MarketplaceEntitlement.objects.filter(order=order).exists():
            report.issue(
                "order_missing_entitlement",
                CRITICAL,
                order=order,
                detail="Paid order had no entitlement; reconciliation restored access.",
                repaired=True,
            )
        else:
            # The buyer's entitlement for this item belongs to another order, so
            # creating a second one would violate ownership. A human must decide.
            report.issue(
                "order_entitlement_conflict",
                CRITICAL,
                order=order,
                detail="An entitlement for this buyer and item belongs to another order.",
            )
    if sale_missing and sale_created:
        report.issue(
            "order_missing_sale",
            WARNING,
            order=order,
            detail="Paid order had no creator sale record; reconciliation recreated it.",
            repaired=True,
        )
    if entitlement_created:
        services.notify_order_paid(order)


def _audit_paid_orders(report, limit):
    """Check the invariants every fully paid order must satisfy."""
    paid = MarketplaceOrder.objects.filter(state=MarketplaceOrder.State.PAID)
    missing = paid.filter(entitlement__isnull=True) | paid.filter(creator_sale__isnull=True)
    ids = set(missing.values_list("pk", flat=True)[:limit])
    ids.update(paid.order_by("-paid_at").values_list("pk", flat=True)[:limit])
    if len(ids) > limit * 2:
        ids = set(list(ids)[: limit * 2])
    orders = (
        paid.filter(pk__in=ids)
        .select_related("item", "creator_sale")
        .prefetch_related("payments")
        .order_by("-paid_at")
    )
    for order in orders:
        report.scan_order(order.pk)
        payments = list(order.payments.all())
        for payment in payments:
            report.scan_payment(payment.pk)

        total = sum(payment.amount_nsat for payment in payments)
        if _settlement_proven(payments, total):
            _repair_settlement(report, order)
        if total != order.unit_amount_nsat:
            report.issue(
                "payment_amount_mismatch",
                CRITICAL,
                order=order,
                detail=f"Transfers total {total} NSAT but the order was priced at {order.unit_amount_nsat} NSAT.",
            )
        unconfirmed = [payment.role for payment in payments if payment.state != OrderPayment.State.CONFIRMED]
        if unconfirmed:
            report.issue(
                "paid_without_confirmed_payment",
                CRITICAL,
                order=order,
                detail=f"Order is paid but these transfers are not confirmed: {', '.join(sorted(unconfirmed))}.",
            )
        if order.paid_at is None:
            report.issue("paid_without_timestamp", WARNING, order=order, detail="Order is paid but has no paid_at.")

        sale = getattr(order, "creator_sale", None)
        if sale is None:
            # A deleted creator removes their sale row by design; only report the
            # missing record while the creator still exists.
            continue
        if (
            sale.gross_nsat != order.unit_amount_nsat
            or sale.platform_fee_nsat != order.platform_fee_nsat
            or sale.creator_proceeds_nsat != order.creator_proceeds_nsat
        ):
            report.issue(
                "sale_amount_mismatch",
                CRITICAL,
                order=order,
                detail="The creator sale amounts disagree with the order snapshot.",
            )
        if not sale.tx_hash:
            report.issue(
                "sale_missing_tx_hash",
                WARNING,
                order=order,
                detail="The sale record has no creator transfer hash for payout reconciliation.",
            )


def _scan_payments(report, order):
    payments = list(order.payments.all())
    for payment in payments:
        report.scan_payment(payment.pk)
    return payments


def _audit_open_orders(report, limit):
    """Every transfer confirmed, yet the order stayed open: access was missed."""
    orders = (
        MarketplaceOrder.objects.filter(
            state__in=OPEN_STATES,
            payments__state=OrderPayment.State.CONFIRMED,
        )
        .select_related("item")
        .prefetch_related("payments")
        .distinct()
        .order_by("-created_at")[:limit]
    )
    for order in orders:
        if order.pk in report.sync_failures:
            # Already reported as order_sync_failed; one cause, one finding.
            continue
        report.scan_order(order.pk)
        payments = _scan_payments(report, order)
        if not payments or any(payment.state != OrderPayment.State.CONFIRMED for payment in payments):
            continue
        report.issue(
            "order_fully_paid_but_open",
            CRITICAL,
            order=order,
            detail=(
                f"All {len(payments)} transfer(s) confirmed but the order is still {order.state}; "
                "the buyer has no access."
            ),
        )


def _audit_closed_orders(report, limit):
    """A closed order must never keep a transfer the chain accepted.

    Closing is fail-closed: one failed transfer of a multi-transfer payment ends
    the order even if another one confirmed. That accepted transfer is still
    money out of the buyer's wallet, so it is reported for a human to refund or
    grant manually. Nothing is rewritten, because only an operator can decide
    whether the buyer should be refunded or given access.
    """
    closed = (
        MarketplaceOrder.objects.filter(
            state__in=(MarketplaceOrder.State.EXPIRED, MarketplaceOrder.State.FAILED),
            payments__state=OrderPayment.State.CONFIRMED,
        )
        .select_related("item")
        .prefetch_related("payments")
        .distinct()
        .order_by("-created_at")[:limit]
    )
    for order in closed:
        report.scan_order(order.pk)
        payments = _scan_payments(report, order)
        confirmed = sorted(payment.role for payment in payments if payment.state == OrderPayment.State.CONFIRMED)
        if not confirmed:
            continue
        report.issue(
            "closed_order_with_confirmed_payment",
            CRITICAL,
            order=order,
            detail=(
                f"Order is {order.state} but the {', '.join(confirmed)} transfer confirmed on chain; "
                "the buyer paid and got no access."
            ),
        )


def _audit_entitlements(report, limit):
    """Active rights must always be backed by an order the chain settled."""
    entitlements = (
        MarketplaceEntitlement.objects.filter(revoked_at__isnull=True)
        .exclude(order__state=MarketplaceOrder.State.PAID)
        .select_related("order", "item")
        .order_by("acquired_at")[:limit]
    )
    for entitlement in entitlements:
        report.scan_order(entitlement.order_id)
        report.issue(
            "entitlement_without_paid_order",
            CRITICAL,
            order=entitlement.order,
            detail=f"Active access to “{entitlement.item.title}” belongs to an order in state {entitlement.order.state}.",
        )


def _recheck_confirmed_payments(report, limit):
    """Detect a reorg: the ledger confirmed a transfer the chain no longer has."""
    days = recheck_days()
    if days <= 0:
        return
    since = timezone.now() - timedelta(days=days)
    payments = (
        OrderPayment.objects.filter(
            state=OrderPayment.State.CONFIRMED,
            tx_hash__gt="",
            confirmed_at__gte=since,
        )
        .select_related("order")
        # Least recently verified first: a busy week would otherwise push older
        # confirmed transfers out of the page and they would never be re-read.
        .order_by(F("chain_checked_at").asc(nulls_first=True), "confirmed_at")[: min(limit, 100)]
    )
    for payment in payments:
        report.scan_payment(payment.pk)
        verdict = _chain_verdict(payment)
        if verdict is None:
            # Unknown stays unmarked so the next pass retries it first.
            continue
        report.chain_check()
        payment.chain_checked_at = timezone.now()
        payment.save(update_fields=["chain_checked_at"])
        if _confirmed(verdict):
            continue
        report.issue(
            "payment_no_longer_confirmed",
            CRITICAL,
            order=payment.order,
            payment=payment,
            detail=(
                f"The indexer now reports {verdict['status']} for {payment.tx_hash[:16]}…; "
                "rights were granted, so review before revoking anything."
            ),
        )


def _summarise(run):
    prefix = "Dry run — " if run.dry_run else ""
    return (
        f"{prefix}{run.orders_scanned} order(s), {run.payments_scanned} payment(s), "
        f"{run.chain_checks} chain check(s): {run.issues_found} issue(s), "
        f"{run.critical_issues} critical, {run.repairs_applied} repaired."
    )[:300]


def close_abandoned_runs():
    """Fail runs left behind by a killed process so the report stays honest."""
    cutoff = timezone.now() - timedelta(minutes=RUN_STALE_MINUTES)
    closed = MarketplaceReconciliationRun.objects.filter(
        status=MarketplaceReconciliationRun.Status.RUNNING,
        started_at__lt=cutoff,
    ).update(
        status=MarketplaceReconciliationRun.Status.FAILED,
        error="The pass did not finish; its process stopped before the report was written.",
        finished_at=timezone.now(),
    )
    if closed:
        logger.warning("closed %s abandoned marketplace reconciliation run(s)", closed)
    return closed


def run_reconciliation(*, trigger=None, source=MarketplaceReconciliationRun.Source.COMMAND, dry_run=False, limit=500, check_chain=True):
    """Compare the chain with the ledger and record an admin-readable report."""
    limit = min(max(int(limit), 1), 2_000)
    close_abandoned_runs()
    run = MarketplaceReconciliationRun.objects.create(
        source=source,
        dry_run=bool(dry_run),
        triggered_by=trigger,
    )
    report = Report(run)
    try:
        # Order matters: settle what the chain already confirmed, then audit the
        # resulting ledger so a late settlement is not reported as a gap.
        _settle_submitted_payments(report, limit, check_chain)
        _audit_paid_orders(report, limit)
        _audit_open_orders(report, limit)
        _audit_closed_orders(report, limit)
        _audit_entitlements(report, limit)
        if check_chain:
            _recheck_confirmed_payments(report, limit)
    except Exception as error:
        run.status = MarketplaceReconciliationRun.Status.FAILED
        run.error = f"{type(error).__name__}: {error}"[:2000]
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at"])
        logger.exception("marketplace reconciliation failed")
        raise

    run.status = MarketplaceReconciliationRun.Status.COMPLETED
    run.finished_at = timezone.now()
    run.orders_scanned = len(report.order_ids)
    run.payments_scanned = len(report.payment_ids)
    run.chain_checks = report.chain_checks
    run.issues_found = report.issues
    run.critical_issues = report.critical
    run.repairs_applied = report.repairs
    run.summary = _summarise(run)
    run.save(
        update_fields=[
            "status",
            "finished_at",
            "orders_scanned",
            "payments_scanned",
            "chain_checks",
            "issues_found",
            "critical_issues",
            "repairs_applied",
            "summary",
        ]
    )
    MarketplaceAuditEvent.objects.create(
        actor=trigger,
        action="reconciliation.completed",
        metadata={
            "run": str(run.pk),
            "dry_run": run.dry_run,
            "issues_found": run.issues_found,
            "critical_issues": run.critical_issues,
            "repairs_applied": run.repairs_applied,
        },
    )
    return run
