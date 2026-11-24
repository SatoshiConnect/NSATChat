"""NSAT settlement for marketplace orders.

Money moves only through NSAT Mainnet payment envelopes signed on the buyer's
device. Every transfer is re-verified server-side (signature, network, source,
payee, exact amount) and fulfilment waits for the indexer to confirm it. The
legacy no-payment demo is a separate, default-off flag.
"""

import binascii
import hashlib
import json
import logging
import re
from datetime import timedelta
from urllib.error import HTTPError, URLError

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.wallet_integration.models import WalletLink
from apps.wallet_integration.views import (
    ADDRESS_RE,
    MAINNET_ID,
    confirmation_for_hash,
    submit_signed_envelope,
    verify_payment_envelope,
)

from .models import (
    CreatorNotification,
    CreatorSale,
    DigitalItem,
    MarketplaceAuditEvent,
    MarketplaceEntitlement,
    MarketplaceOrder,
    OrderPayment,
)

logger = logging.getLogger(__name__)

MAX_NSAT = 2**63 - 1
GATEWAY_TRANSIENT_ERRORS = (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError)


class MarketplaceError(Exception):
    """A refusal the API turns into a client-visible code and status."""

    def __init__(self, code, status=400):
        super().__init__(code)
        self.code = code
        self.status = status


def live_payments_enabled():
    return bool(settings.MARKETPLACE_LIVE_PAYMENTS)


def simulations_enabled():
    return bool(settings.MARKETPLACE_ALLOW_SIMULATED_PURCHASES)


def purchase_mode():
    if live_payments_enabled():
        return "nsat"
    if simulations_enabled():
        return "simulation"
    return "closed"


def platform_fee_bps():
    try:
        bps = int(settings.MARKETPLACE_PLATFORM_FEE_BPS)
    except (TypeError, ValueError):
        raise MarketplaceError("marketplace_misconfigured", status=503)
    if bps < 0 or bps > 10000:
        raise MarketplaceError("marketplace_misconfigured", status=503)
    return bps


def treasury_address():
    return str(settings.MARKETPLACE_TREASURY_ADDRESS or "").strip().upper()


def order_ttl_seconds():
    try:
        ttl = int(settings.MARKETPLACE_ORDER_TTL_SECONDS)
    except (TypeError, ValueError):
        ttl = 900
    return min(max(ttl, 120), 86_400)


def split_amounts(unit_amount, bps):
    """Integer-only split so rounding never creates or destroys a satoshi."""
    if unit_amount <= 0 or unit_amount > MAX_NSAT:
        raise MarketplaceError("invalid_amount")
    fee = unit_amount * bps // 10000
    proceeds = unit_amount - fee
    if proceeds <= 0:
        raise MarketplaceError("marketplace_misconfigured", status=503)
    return fee, proceeds


def linked_address(user):
    link = WalletLink.objects.filter(user=user).only("address").first()
    return link.address if link else ""


def order_payload(order, now=None):
    now = now or timezone.now()
    payments = list(order.payments.all().order_by("role"))
    return {
        "id": str(order.id),
        "state": order.state,
        "item": {
            "id": order.item_id,
            "title": order.item.title,
            "kind": order.item.kind,
        },
        "unit_amount_nsat": order.unit_amount_nsat,
        "total_due_nsat": order.total_due_nsat,
        "platform_fee_bps": order.platform_fee_bps,
        "platform_fee_nsat": order.platform_fee_nsat,
        "creator_proceeds_nsat": order.creator_proceeds_nsat,
        "network": order.network,
        "buyer_address": linked_address(order.buyer),
        "created_at": order.created_at.isoformat(),
        "expires_at": order.expires_at.isoformat(),
        "seconds_remaining": max(0, int((order.expires_at - now).total_seconds())),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "payments": [
            {
                "role": payment.role,
                "payee_address": payment.payee_address,
                "amount_nsat": payment.amount_nsat,
                "state": payment.state,
                "tx_hash": payment.tx_hash,
                "ledger": payment.ledger,
            }
            for payment in payments
        ],
    }


def _close_stale_orders(buyer, item, now):
    MarketplaceOrder.objects.filter(
        buyer=buyer,
        item=item,
        state__in=[MarketplaceOrder.State.AWAITING_PAYMENT, MarketplaceOrder.State.PARTIALLY_PAID],
        expires_at__lt=now,
    ).exclude(payments__tx_hash__gt="").update(state=MarketplaceOrder.State.EXPIRED)


def create_order(*, buyer, item, idempotency_key):
    """Price an item, snapshot its split and open the transfers to be signed."""
    if not live_payments_enabled():
        raise MarketplaceError("marketplace_payments_unavailable", status=503)
    if item.state != DigitalItem.State.APPROVED:
        raise MarketplaceError("item_unavailable", status=404)
    if not item.creator_id:
        raise MarketplaceError("item_unavailable", status=404)
    if item.creator_id == buyer.id:
        raise MarketplaceError("cannot_buy_own_item")
    if MarketplaceEntitlement.objects.filter(owner=buyer, item=item).exists():
        # Paying twice for the same item must never be possible.
        raise MarketplaceError("already_owned", status=409)
    unit_amount = int(item.proposed_price_nsat)
    bps = platform_fee_bps()
    platform_fee, creator_proceeds = split_amounts(unit_amount, bps)
    treasury = treasury_address()
    if platform_fee:
        if not ADDRESS_RE.fullmatch(treasury):
            # A fee without a verified destination must never silently become a
            # donation to the creator or a locked balance.
            raise MarketplaceError("marketplace_misconfigured", status=503)
    buyer_address = linked_address(buyer)
    if not buyer_address:
        raise MarketplaceError("wallet_not_linked", status=409)
    creator_address = linked_address(item.creator)
    if not ADDRESS_RE.fullmatch(creator_address):
        raise MarketplaceError("creator_wallet_unavailable", status=409)

    existing = MarketplaceOrder.objects.filter(buyer=buyer, idempotency_key=idempotency_key).first()
    if existing:
        if existing.item_id != item.pk:
            raise MarketplaceError("idempotency_key_reused", status=409)
        return existing

    now = timezone.now()
    _close_stale_orders(buyer, item, now)
    age = MarketplaceOrder.objects.filter(
        buyer=buyer,
        item=item,
        state__in=[MarketplaceOrder.State.AWAITING_PAYMENT, MarketplaceOrder.State.PARTIALLY_PAID],
        expires_at__gte=now,
    ).exists()
    if age:
        raise MarketplaceError("order_already_open", status=409)

    try:
        with transaction.atomic():
            order = MarketplaceOrder.objects.create(
                buyer=buyer,
                item=item,
                idempotency_key=idempotency_key,
                unit_amount_nsat=unit_amount,
                platform_fee_bps=bps,
                platform_fee_nsat=platform_fee,
                creator_proceeds_nsat=creator_proceeds,
                network=MAINNET_ID,
                treasury_address=treasury if platform_fee else "",
                expires_at=now + timedelta(seconds=order_ttl_seconds()),
            )
            OrderPayment.objects.create(
                order=order,
                role=OrderPayment.Role.CREATOR,
                payee_address=creator_address,
                amount_nsat=creator_proceeds,
            )
            if platform_fee:
                OrderPayment.objects.create(
                    order=order,
                    role=OrderPayment.Role.PLATFORM,
                    payee_address=treasury,
                    amount_nsat=platform_fee,
                )
            MarketplaceAuditEvent.objects.create(
                actor=buyer,
                item=item,
                action="order.created",
                metadata={
                    "order": str(order.id),
                    "unit_amount_nsat": unit_amount,
                    "platform_fee_bps": bps,
                    "platform_fee_nsat": platform_fee,
                },
            )
    except IntegrityError:
        duplicate = MarketplaceOrder.objects.filter(buyer=buyer, idempotency_key=idempotency_key).first()
        if duplicate:
            return duplicate
        raise MarketplaceError("order_conflict", status=409)
    return order


def _validated_envelope(envelope, payment, buyer_address):
    if not isinstance(envelope, str) or len(envelope) > 65_536:
        raise MarketplaceError("invalid_signed_envelope")
    if not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", envelope):
        raise MarketplaceError("invalid_signed_envelope")
    try:
        verified = verify_payment_envelope(envelope)
    except (binascii.Error, ValueError):
        raise MarketplaceError("invalid_signed_envelope")
    if verified["source"] != buyer_address:
        raise MarketplaceError("envelope_source_mismatch")
    if verified["destination"] != payment.payee_address:
        raise MarketplaceError("envelope_payee_mismatch")
    if verified["amount"] != payment.amount_nsat:
        raise MarketplaceError("envelope_amount_mismatch")
    return verified


def _hash_used_by_another_order(tx_hash, payment_id):
    return OrderPayment.objects.filter(tx_hash=tx_hash).exclude(pk=payment_id).exists()


def record_order_payment(*, order, role, envelope):
    """Verify and submit one signed tranche of an order.

    A signed transfer is currency: it must never be accepted twice, even by
    another order. That is checked before submission and enforced again by the
    unique transaction hash, so a racing request still gets a clear refusal
    instead of a server error.
    """
    if not live_payments_enabled():
        raise MarketplaceError("marketplace_payments_unavailable", status=503)
    role = str(role or "").strip().lower()
    if role not in OrderPayment.Role.values:
        raise MarketplaceError("unknown_payment_role", status=404)
    now = timezone.now()
    verified_hash = ""
    try:
        with transaction.atomic():
            locked = MarketplaceOrder.objects.select_for_update().get(pk=order.pk)
            payment = locked.payments.filter(role=role).first()
            if not payment:
                raise MarketplaceError("unknown_payment_role", status=404)
            if locked.state == MarketplaceOrder.State.PAID:
                return locked
            if locked.state in {MarketplaceOrder.State.EXPIRED, MarketplaceOrder.State.FAILED}:
                raise MarketplaceError("order_closed", status=409)
            if payment.state == OrderPayment.State.CONFIRMED:
                return locked
            if payment.tx_hash:
                raise MarketplaceError("payment_already_submitted", status=409)
            if locked.expires_at <= now:
                locked.state = MarketplaceOrder.State.EXPIRED
                locked.save(update_fields=["state"])
                raise MarketplaceError("order_expired", status=409)
            buyer_address = linked_address(locked.buyer)
            if not buyer_address:
                raise MarketplaceError("wallet_not_linked", status=409)
            verified = _validated_envelope(envelope, payment, buyer_address)
            verified_hash = verified["hash"]
            if _hash_used_by_another_order(verified_hash, payment.pk):
                raise MarketplaceError("payment_already_used", status=409)
            submitted_at = int(now.timestamp())
            try:
                gateway_status = submit_signed_envelope(envelope)
            except MarketplaceError:
                raise
            except GATEWAY_TRANSIENT_ERRORS:
                raise MarketplaceError("wallet_unavailable", status=503)
            if gateway_status not in {"PENDING", "DUPLICATE"}:
                raise MarketplaceError("wallet_gateway_rejected", status=502)
            payment.tx_hash = verified_hash
            payment.submitted_at = submitted_at
            payment.save(update_fields=["tx_hash", "submitted_at"])
            if locked.state == MarketplaceOrder.State.AWAITING_PAYMENT:
                locked.state = MarketplaceOrder.State.PARTIALLY_PAID
                locked.save(update_fields=["state"])
            MarketplaceAuditEvent.objects.create(
                actor=locked.buyer,
                item=locked.item,
                action="order.payment_submitted",
                metadata={"order": str(locked.id), "role": payment.role, "tx_hash": payment.tx_hash},
            )
    except IntegrityError:
        # Two orders raced with the same signature; the unique hash is the
        # final arbiter and the loser is told the transfer is already used.
        if verified_hash and OrderPayment.objects.filter(tx_hash=verified_hash).exists():
            raise MarketplaceError("payment_already_used", status=409)
        raise
    return MarketplaceOrder.objects.get(pk=order.pk)


def buyer_reference(user_id):
    """Stable, non-reversible reference kept after an account is deleted."""
    return hashlib.sha256(f"{settings.SECRET_KEY}:buyer:{user_id}".encode("utf-8")).hexdigest()[:32]


def revoke_entitlement(entitlement, *, actor=None, reason=""):
    """End access explicitly, keeping an audit trail and telling the buyer."""
    reason = str(reason or "")[:300]
    with transaction.atomic():
        locked = MarketplaceEntitlement.objects.select_for_update().get(pk=entitlement.pk)
        if locked.revoked_at:
            return locked
        locked.revoked_at = timezone.now()
        locked.revoked_reason = reason
        locked.revoked_by = actor
        locked.save(update_fields=["revoked_at", "revoked_reason", "revoked_by"])
        MarketplaceAuditEvent.objects.create(
            actor=actor,
            item=locked.item,
            action="entitlement.revoked",
            metadata={"owner": locked.owner_id, "order": str(locked.order_id), "reason": reason},
        )
        CreatorNotification.objects.create(
            recipient=locked.owner,
            actor=actor,
            item=locked.item,
            event_type="entitlement_revoked",
            message=f"Access to “{locked.item.title}” was revoked. {reason}".strip()[:200],
        )
    return locked


def restore_entitlement(entitlement, *, actor=None, reason=""):
    """Undo a mistaken revocation, keeping both events in the audit trail."""
    reason = str(reason or "")[:300]
    with transaction.atomic():
        locked = MarketplaceEntitlement.objects.select_for_update().get(pk=entitlement.pk)
        if not locked.revoked_at:
            return locked
        previous_reason = locked.revoked_reason
        locked.revoked_at = None
        locked.revoked_reason = ""
        locked.revoked_by = None
        locked.save(update_fields=["revoked_at", "revoked_reason", "revoked_by"])
        MarketplaceAuditEvent.objects.create(
            actor=actor,
            item=locked.item,
            action="entitlement.restored",
            metadata={
                "owner": locked.owner_id,
                "order": str(locked.order_id),
                "previous_reason": previous_reason,
                "reason": reason,
            },
        )
        CreatorNotification.objects.create(
            recipient=locked.owner,
            actor=actor,
            item=locked.item,
            event_type="entitlement_restored",
            message=f"Access to “{locked.item.title}” was restored.".strip()[:200],
        )
    return locked


def _apply_confirmation(payment, verdict):
    if verdict["status"] == "confirmed" and verdict["success"] is True:
        payment.state = OrderPayment.State.CONFIRMED
        payment.confirmed_at = timezone.now()
        payment.ledger = verdict["ledger"]
        payment.save(update_fields=["state", "confirmed_at", "ledger"])
    elif verdict["status"] == "failed" or (verdict["status"] == "confirmed" and verdict["success"] is False):
        payment.state = OrderPayment.State.FAILED
        payment.save(update_fields=["state"])


def notify_order_paid(order):
    """Push an unlock nudge to the buyer's open tabs.

    Best-effort: the REST library stays authoritative, so a missing channel
    layer or a disconnected socket must never fail a confirmed purchase.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            f"chat_inbox_{order.buyer_id}",
            {
                "type": "inbox.marketplace_paid",
                "order_id": str(order.pk),
                "item_id": order.item_id,
                "item_title": order.item.title,
            },
        )
    except Exception:  # noqa: BLE001 - delivery is best-effort
        logger.warning("marketplace realtime unlock event failed for order %s", order.pk, exc_info=True)


def _fulfil(order):
    with transaction.atomic():
        locked = MarketplaceOrder.objects.select_for_update().get(pk=order.pk)
        if locked.state == MarketplaceOrder.State.PAID:
            # Already fulfilled: never re-notify or duplicate the sale record.
            return locked
        if not locked.item.creator_id:
            raise MarketplaceError("item_unavailable", status=409)
        creator_payment = locked.payments.filter(role=OrderPayment.Role.CREATOR).first()
        if not MarketplaceEntitlement.objects.filter(owner=locked.buyer, item=locked.item).exists():
            MarketplaceEntitlement.objects.create(owner=locked.buyer, item=locked.item, order=locked)
        CreatorSale.objects.get_or_create(
            order=locked,
            defaults={
                "order_reference": locked.pk,
                "buyer_reference": buyer_reference(locked.buyer_id),
                "creator": locked.item.creator,
                "item": locked.item,
                "gross_nsat": locked.unit_amount_nsat,
                "platform_fee_nsat": locked.platform_fee_nsat,
                "creator_proceeds_nsat": locked.creator_proceeds_nsat,
                "tx_hash": creator_payment.tx_hash if creator_payment else "",
            },
        )
        locked.state = MarketplaceOrder.State.PAID
        locked.paid_at = timezone.now()
        locked.save(update_fields=["state", "paid_at"])
        MarketplaceAuditEvent.objects.create(
            actor=locked.buyer,
            item=locked.item,
            action="order.paid",
            metadata={
                "order": str(locked.id),
                "unit_amount_nsat": locked.unit_amount_nsat,
                "platform_fee_nsat": locked.platform_fee_nsat,
            },
        )
        CreatorNotification.objects.create(
            recipient=locked.item.creator,
            actor=locked.buyer,
            item=locked.item,
            event_type="sale",
            message=f"Sold “{locked.item.title}” for {locked.creator_proceeds_nsat} NSAT",
        )
    settled = MarketplaceOrder.objects.select_related("item").get(pk=order.pk)
    # Commit has happened, so a client that re-reads the library now sees the
    # entitlement. Realtime delivery is best-effort and never blocks the sale.
    notify_order_paid(settled)
    return settled


def sync_order(order, *, allow_terminal=True):
    """Poll the indexer for every submitted tranche and fulfil once all confirm."""
    order = MarketplaceOrder.objects.get(pk=order.pk)
    if order.state in {MarketplaceOrder.State.PAID, MarketplaceOrder.State.FAILED}:
        return order
    if order.state == MarketplaceOrder.State.EXPIRED and not order.payments.exclude(tx_hash="").exists():
        return order
    for payment in order.payments.all():
        if payment.state != OrderPayment.State.PENDING or not payment.tx_hash or not payment.submitted_at:
            continue
        try:
            verdict = confirmation_for_hash(payment.tx_hash, payment.submitted_at)
        except GATEWAY_TRANSIENT_ERRORS:
            continue
        _apply_confirmation(payment, verdict)
    payments = list(order.payments.all())
    now = timezone.now()
    if any(payment.state == OrderPayment.State.FAILED for payment in payments):
        MarketplaceOrder.objects.filter(pk=order.pk).exclude(state=MarketplaceOrder.State.PAID).update(
            state=MarketplaceOrder.State.FAILED
        )
        return MarketplaceOrder.objects.get(pk=order.pk)
    if payments and all(payment.state == OrderPayment.State.CONFIRMED for payment in payments):
        return _fulfil(order)
    if any(payment.state == OrderPayment.State.CONFIRMED for payment in payments):
        if order.state != MarketplaceOrder.State.PARTIALLY_PAID:
            MarketplaceOrder.objects.filter(pk=order.pk).update(state=MarketplaceOrder.State.PARTIALLY_PAID)
    elif allow_terminal and order.expires_at <= now and not any(payment.tx_hash for payment in payments):
        MarketplaceOrder.objects.filter(pk=order.pk).exclude(state=MarketplaceOrder.State.PAID).update(
            state=MarketplaceOrder.State.EXPIRED
        )
    return MarketplaceOrder.objects.get(pk=order.pk)


def expire_open_orders(limit=500):
    """Close orders nobody paid inside their window (safe to run periodically)."""
    now = timezone.now()
    stale = (
        MarketplaceOrder.objects.filter(
            state__in=[MarketplaceOrder.State.AWAITING_PAYMENT, MarketplaceOrder.State.PARTIALLY_PAID],
            expires_at__lt=now,
        )
        .exclude(payments__tx_hash__gt="")
        .only("pk")[:limit]
    )
    ids = [order.pk for order in stale]
    if not ids:
        return 0
    return MarketplaceOrder.objects.filter(
        pk__in=ids,
        state__in=[MarketplaceOrder.State.AWAITING_PAYMENT, MarketplaceOrder.State.PARTIALLY_PAID],
    ).update(state=MarketplaceOrder.State.EXPIRED)
