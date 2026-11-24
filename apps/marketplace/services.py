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
from django.contrib.auth import get_user_model
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
    MAX_SALE_PRICE_NSAT,
    MIN_SALE_PRICE_NSAT,
    CreatorNotification,
    CreatorSale,
    DigitalItem,
    GiftEvent,
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
        "gift": (
            {
                "recipient_id": order.gift_recipient_id,
                "recipient_name": order.gift_recipient_name,
                "status_id": order.gift_status_id,
            }
            if order.gift_recipient_id
            else None
        ),
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


def _validate_gift(buyer, item, recipient, gift_status, now):
    """Refuse a gift that would pay for something the recipient cannot keep."""
    if recipient is None:
        raise MarketplaceError("gift_status_required")
    if recipient.pk == buyer.pk:
        raise MarketplaceError("cannot_gift_to_self")
    if recipient.pk == item.creator_id:
        raise MarketplaceError("cannot_gift_to_creator")
    if not recipient.is_active or recipient.is_deleted:
        raise MarketplaceError("recipient_unavailable", status=404)
    if gift_status is None:
        raise MarketplaceError("gift_status_required")
    if gift_status.user_id != recipient.pk:
        raise MarketplaceError("gift_status_not_recipients", status=409)
    if gift_status.is_deleted or gift_status.expires_at <= now:
        # The gift is tied to a Story that is still live, so paying for an
        # expired one would buy an item nobody can open from that Story.
        raise MarketplaceError("gift_status_expired", status=409)
    from apps.accounts.models import Contact
    from apps.status.policies import can_view_status

    contact_ids = set(Contact.objects.filter(owner=buyer).values_list("contact_user_id", flat=True))
    if not can_view_status(gift_status, buyer, contact_ids):
        raise MarketplaceError("gift_status_not_visible", status=403)
    if MarketplaceEntitlement.objects.filter(owner=recipient, item=item, revoked_at__isnull=True).exists():
        raise MarketplaceError("recipient_already_owns", status=409)


def create_order(*, buyer, item, idempotency_key, gift_recipient=None, gift_status=None):
    """Price an item, snapshot its split and open the transfers to be signed.

    With ``gift_recipient`` the buyer pays exactly the same transfers, but the
    entitlement lands in the recipient's library tied to the Story the buyer was
    watching when they sent it.
    """
    if not live_payments_enabled():
        raise MarketplaceError("marketplace_payments_unavailable", status=503)
    if item.state != DigitalItem.State.APPROVED:
        raise MarketplaceError("item_unavailable", status=404)
    if not item.creator_id:
        raise MarketplaceError("item_unavailable", status=404)
    if item.creator_id == buyer.id:
        raise MarketplaceError("cannot_buy_own_item")
    is_gift = gift_recipient is not None or gift_status is not None
    if is_gift:
        _validate_gift(buyer, item, gift_recipient, gift_status, timezone.now())
    elif MarketplaceEntitlement.objects.filter(owner=buyer, item=item).exists():
        # Paying twice for the same item must never be possible.
        raise MarketplaceError("already_owned", status=409)
    unit_amount = int(item.proposed_price_nsat)
    if not MIN_SALE_PRICE_NSAT <= unit_amount <= MAX_SALE_PRICE_NSAT:
        # A listing without a settleable price cannot become an order: a zero
        # amount is not a transfer, and an oversized one is not what the human
        # approved in their wallet. The catalog already shows it as closed, so
        # the API answers with the same meaning instead of a generic refusal.
        raise MarketplaceError("item_not_for_sale", status=409)
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
        if existing.item_id != item.pk or (existing.gift_recipient_id or None) != (gift_recipient.pk if gift_recipient else None):
            raise MarketplaceError("idempotency_key_reused", status=409)
        return existing

    now = timezone.now()
    try:
        with transaction.atomic():
            # Serialise checkout per buyer. Without this lock two tabs posting
            # different idempotency keys in the same instant both pass the
            # open-order check and become payable, so one listing could be paid
            # for twice. The replay and ownership checks are repeated here so a
            # request that waited on the lock sees what the winner committed.
            get_user_model().objects.select_for_update().only("pk").get(pk=buyer.pk)
            replay = MarketplaceOrder.objects.filter(buyer=buyer, idempotency_key=idempotency_key).first()
            if replay:
                if replay.item_id != item.pk or (replay.gift_recipient_id or None) != (gift_recipient.pk if gift_recipient else None):
                    raise MarketplaceError("idempotency_key_reused", status=409)
                return replay
            _close_stale_orders(buyer, item, now)
            age = MarketplaceOrder.objects.filter(
                buyer=buyer,
                item=item,
                state__in=[MarketplaceOrder.State.AWAITING_PAYMENT, MarketplaceOrder.State.PARTIALLY_PAID],
                expires_at__gte=now,
            ).exists()
            if age:
                raise MarketplaceError("order_already_open", status=409)
            if MarketplaceEntitlement.objects.filter(owner_id=buyer.pk, item_id=item.pk).exists() and not is_gift:
                raise MarketplaceError("already_owned", status=409)
            if is_gift and MarketplaceEntitlement.objects.filter(
                owner_id=gift_recipient.pk, item_id=item.pk, revoked_at__isnull=True
            ).exists():
                raise MarketplaceError("recipient_already_owns", status=409)
            gift_name = ""
            if is_gift:
                profile = getattr(gift_recipient, "profile", None)
                gift_name = (getattr(profile, "display_name", "") or "").strip() or f"User {gift_recipient.pk}"
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
                gift_recipient=gift_recipient,
                gift_recipient_name=gift_name,
                gift_status=gift_status,
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
                    "gift_recipient_id": gift_recipient.pk if gift_recipient else None,
                    "gift_status_id": gift_status.pk if gift_status else None,
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
            if MarketplaceEntitlement.objects.filter(
                owner_id=locked.buyer_id, item_id=locked.item_id, revoked_at__isnull=True
            ).exclude(order_id=locked.pk).exists():
                # The buyer already owns this item through another order (for
                # example a second order created before duplicate checkouts were
                # serialised). Accepting a transfer here would charge twice and
                # grant nothing, so it is refused before the gateway is called.
                raise MarketplaceError("already_owned", status=409)
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
            # A gift unlocks for the recipient, so their open tab is the one
            # that must refresh when the payment confirms.
            f"chat_inbox_{order.gift_recipient_id or order.buyer_id}",
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
        ensure_settlement_records(locked)
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
                "gift_recipient_id": locked.gift_recipient_id,
            },
        )
        CreatorNotification.objects.create(
            recipient=locked.item.creator,
            actor=locked.buyer,
            item=locked.item,
            event_type="sale",
            message=f"Sold “{locked.item.title}” for {locked.creator_proceeds_nsat} NSAT",
        )
        if locked.gift_recipient_id:
            CreatorNotification.objects.create(
                recipient_id=locked.gift_recipient_id,
                actor=locked.buyer,
                item=locked.item,
                event_type="gift_received",
                message=f"You received “{locked.item.title}” as a gift",
            )
    settled = MarketplaceOrder.objects.select_related("item").get(pk=order.pk)
    # Commit has happened, so a client that re-reads the library now sees the
    # entitlement. Realtime delivery is best-effort and never blocks the sale.
    notify_order_paid(settled)
    return settled


def ensure_settlement_records(order):
    """Create the entitlement and creator sale of a confirmed order, once each.

    Shared by fulfilment and reconciliation so a paid order always ends with
    exactly one entitlement and one sale record, whether the checkout request,
    the settling command or a later repair got there first.
    """
    creator_payment = order.payments.filter(role=OrderPayment.Role.CREATOR).first()
    # A gift opens the item for the recipient; the buyer paid for it but never
    # owned it, so their library must not gain a second copy.
    owner_id = order.gift_recipient_id or order.buyer_id
    _, entitlement_created = MarketplaceEntitlement.objects.get_or_create(
        owner_id=owner_id,
        item_id=order.item_id,
        defaults={"order_id": order.pk},
    )
    if order.gift_recipient_id:
        GiftEvent.objects.get_or_create(
            order=order,
            defaults={
                "sender": order.buyer,
                "recipient_id": order.gift_recipient_id,
                "item": order.item,
                "status_id": order.gift_status_id,
                "simulation_only": False,
            },
        )
    sale_created = False
    if order.item.creator_id:
        _, sale_created = CreatorSale.objects.get_or_create(
            order=order,
            defaults={
                "order_reference": order.pk,
                "buyer_reference": buyer_reference(order.buyer_id),
                "creator": order.item.creator,
                "item": order.item,
                "gross_nsat": order.unit_amount_nsat,
                "platform_fee_nsat": order.platform_fee_nsat,
                "creator_proceeds_nsat": order.creator_proceeds_nsat,
                "tx_hash": creator_payment.tx_hash if creator_payment else "",
            },
        )
    return entitlement_created, sale_created


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
