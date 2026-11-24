import hashlib
import uuid

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponseNotModified
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import services
from .models import (
    CreatorNotification,
    CreatorProfile,
    CreatorSale,
    DigitalItem,
    GiftEvent,
    InventoryItem,
    ItemReport,
    MarketplaceAuditEvent,
    MarketplaceEntitlement,
    MarketplaceOrder,
    OrderPayment,
    PurchaseDispute,
    SimulatedPurchase,
)
from .serializers import (
    CreatorProfileSerializer,
    DigitalItemSerializer,
    EntitlementSerializer,
    GiftEventSerializer,
    InventorySerializer,
    ItemReportSerializer,
    OwnedStickerPackSerializer,
    SimulatedPurchaseSerializer,
    SubmitItemSerializer,
)


class CatalogCursorPagination(CursorPagination):
    """Newest-first pages that stay correct while creators publish.

    Cursor paging carries the position instead of a row offset, so an item
    approved between two requests cannot make a shopper see one row twice or
    skip one. A fixed page size also bounds the response a slow phone downloads.
    """

    page_size = 48
    page_size_query_param = "page_size"
    max_page_size = 96
    ordering = ("-created_at", "-pk")


class CatalogAPIView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = DigitalItemSerializer
    pagination_class = CatalogCursorPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        etag = self._etag(queryset)
        if request.headers.get("If-None-Match") == etag:
            response = HttpResponseNotModified()
        else:
            serializer = self.get_serializer(self.paginate_queryset(queryset), many=True)
            response = self.get_paginated_response(serializer.data)
        response["ETag"] = etag
        # The body carries this viewer's ownership flags, so it must never be
        # stored by a shared cache. A short private window removes most repeat
        # reads while still refreshing an item the buyer just paid for.
        response["Cache-Control"] = "private, max-age=30"
        response["Vary"] = "Authorization"
        return response

    def _etag(self, queryset):
        """Cheap validator for everything this viewer's catalog depends on.

        The body carries per-viewer ownership flags and a listing turns from
        payable to closed when its creator connects a wallet, so counting the
        catalog rows alone is not enough: a buyer who just paid, or whose
        access was revoked, must never be handed a cached page that still says
        the item is for sale. Both aggregates are indexed one-row-per-item
        lookups, far cheaper than serialising a page.
        """
        catalog = queryset.aggregate(
            rows=Count("pk", distinct=True),
            newest=Max("updated_at"),
            sellers_with_wallet=Count("creator__nsat_wallet_link", distinct=True),
        )
        owned = MarketplaceEntitlement.objects.filter(owner=self.request.user).aggregate(
            rows=Count("pk"),
            newest=Max("acquired_at"),
            revoked=Max("revoked_at"),
        )

        def stamp(value):
            return value.isoformat() if value else "0"

        parts = [
            str(self.request.user.pk),
            str(catalog["rows"]),
            stamp(catalog["newest"]),
            str(catalog["sellers_with_wallet"]),
            str(owned["rows"]),
            stamp(owned["newest"]),
            stamp(owned["revoked"]),
            self.request.get_full_path(),
        ]
        return f'"{hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:32]}"'

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            context["owned_ids"] = set(
                MarketplaceEntitlement.objects.filter(owner=self.request.user, revoked_at__isnull=True)
                .values_list("item_id", flat=True)
            )
        return context

    def get_queryset(self):
        qs = DigitalItem.objects.filter(state=DigitalItem.State.APPROVED).select_related(
            "creator", "creator__profile", "creator__creator_profile", "creator__nsat_wallet_link"
        ).prefetch_related("assets")
        kind = self.request.query_params.get("kind")
        query = self.request.query_params.get("q", "").strip()[:100]
        if kind in DigitalItem.Kind.values:
            qs = qs.filter(kind=kind)
        if query:
            qs = qs.filter(Q(title__icontains=query) | Q(description__icontains=query))
        return qs


class SubmitItemAPIView(generics.CreateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = SubmitItemSerializer
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "marketplace_submit"

    def perform_create(self, serializer):
        item = serializer.save(creator=self.request.user, state=DigitalItem.State.PENDING)
        CreatorProfile.objects.get_or_create(user=self.request.user)
        MarketplaceAuditEvent.objects.create(actor=self.request.user, item=item, action="item.submitted")


class InventoryAPIView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = InventorySerializer

    def get_queryset(self):
        return InventoryItem.objects.filter(owner=self.request.user).select_related("item", "item__creator", "item__creator__profile", "item__creator__creator_profile")


class OwnedStickerPacksAPIView(generics.ListAPIView):
    """Full sticker assets are exposed only to users with an inventory grant."""
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = OwnedStickerPackSerializer

    def get_queryset(self):
        # Paid access is independent of the sale state: disabling a listing
        # stops new sales, not what buyers already own. Only an explicit
        # revocation (audited) ends it. Legacy simulated grants still require
        # an approved listing because nobody paid for them.
        paid = Q(entitlements__owner=self.request.user, entitlements__revoked_at__isnull=True)
        legacy = Q(inventory_entries__owner=self.request.user, state=DigitalItem.State.APPROVED)
        return DigitalItem.objects.filter(
            paid | legacy,
            kind=DigitalItem.Kind.STICKER_PACK,
        ).prefetch_related("assets").distinct()


class PurchaseHistoryAPIView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = SimulatedPurchaseSerializer

    def get_queryset(self):
        return SimulatedPurchase.objects.filter(buyer=self.request.user).select_related("item", "item__creator", "item__creator__profile", "item__creator__creator_profile")


class MarketplaceConfigAPIView(APIView):
    """Which settlement flows this deployment runs.

    Shoppers only ever see flows the deployment actually enables: a live
    marketplace must not show an empty "simulations" history, and a demo
    deployment must not advertise NSAT checkout it cannot settle.
    """

    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "marketplace_read"

    def get(self, request):
        try:
            fee_bps = services.platform_fee_bps()
        except services.MarketplaceError:
            fee_bps = None
        return Response({
            "live_payments": services.live_payments_enabled(),
            "simulations": services.simulations_enabled(),
            "platform_fee_bps": fee_bps,
        })


class PurchaseSimulationAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "marketplace_purchase"

    def post(self, request, pk):
        if not services.simulations_enabled():
            # Paid inventory is minted only by a confirmed on-chain order.
            return Response({"code": "simulation_disabled"}, status=status.HTTP_404_NOT_FOUND)
        item = get_object_or_404(DigitalItem, pk=pk, state=DigitalItem.State.APPROVED)
        try:
            key = uuid.UUID(str(request.data.get("idempotency_key", "")))
        except (ValueError, TypeError, AttributeError):
            raise ValidationError({"idempotency_key": "Provide a UUID idempotency key."})
        existing = SimulatedPurchase.objects.filter(buyer=request.user, idempotency_key=key).first()
        if existing:
            if existing.item_id != item.pk:
                return Response({"detail": "This idempotency key was already used for another item."}, status=status.HTTP_409_CONFLICT)
            return Response(self._payload(existing), status=status.HTTP_200_OK)
        try:
            with transaction.atomic():
                purchase = SimulatedPurchase.objects.create(buyer=request.user, item=item, idempotency_key=key, amount_nsat=item.proposed_price_nsat)
                InventoryItem.objects.create(owner=request.user, item=item, purchase=purchase)
                MarketplaceAuditEvent.objects.create(actor=request.user, item=item, action="purchase.simulated", metadata={"purchase_id": str(purchase.pk), "amount_nsat": purchase.amount_nsat})
        except IntegrityError:
            # Concurrent requests may race on the unique idempotency key.
            # Only replay a result for the same item; an unrelated constraint
            # failure or key collision must not be reported as a purchase.
            purchase = SimulatedPurchase.objects.filter(buyer=request.user, idempotency_key=key).first()
            if purchase is None:
                raise
            if purchase.item_id != item.pk:
                return Response({"detail": "This idempotency key was already used for another item."}, status=status.HTTP_409_CONFLICT)
            return Response(self._payload(purchase), status=status.HTTP_200_OK)
        return Response(self._payload(purchase), status=status.HTTP_201_CREATED)

    @staticmethod
    def _payload(purchase):
        return {"id": str(purchase.pk), "state": purchase.state, "simulation_only": True, "on_chain": False, "message": "Simulation only. No NSAT was transferred.", "amount_nsat_proposed": purchase.amount_nsat}


class GiftAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "marketplace_gift"

    def get(self, request):
        received = GiftEvent.objects.filter(recipient=request.user).select_related("item")[:100]
        sent = GiftEvent.objects.filter(sender=request.user).select_related("item")[:100]
        return Response({"received": GiftEventSerializer(received, many=True).data, "sent": GiftEventSerializer(sent, many=True).data})

    def post(self, request):
        item = get_object_or_404(DigitalItem, pk=request.data.get("item_id"), kind=DigitalItem.Kind.GIFT, state=DigitalItem.State.APPROVED)
        recipient_id = request.data.get("recipient_id")
        status_id = request.data.get("status_id")
        if not status_id:
            raise ValidationError({"status_id": "Choose a visible Story to attach this gift to."})
        from apps.accounts.models import User
        recipient = get_object_or_404(User, pk=recipient_id, is_active=True, is_deleted=False)
        target_status = None
        if status_id:
            from apps.status.models import Status
            target_status = get_object_or_404(Status, pk=status_id, user=recipient, is_deleted=False)
            if target_status.is_expired:
                raise ValidationError({"status_id": "This update has expired."})
            from apps.accounts.models import Contact
            from apps.status.policies import can_view_status
            viewers_contacts = set(Contact.objects.filter(owner=request.user).values_list("contact_user_id", flat=True))
            if not can_view_status(target_status, request.user, viewers_contacts):
                raise ValidationError({"status_id": "You cannot send a gift to this update."})
        with transaction.atomic():
            owned = InventoryItem.objects.select_for_update().filter(owner=request.user, item=item).order_by("pk").first()
            if not owned:
                raise ValidationError({"item_id": "Add this gift to your library using the simulation flow first."})
            owned.delete()
            event = GiftEvent.objects.create(sender=request.user, recipient=recipient, item=item, status=target_status)
            MarketplaceAuditEvent.objects.create(actor=request.user, item=item, action="gift.simulated", metadata={"gift_event_id": event.pk, "recipient_id": recipient.pk})
            CreatorNotification.objects.create(recipient=recipient, actor=request.user, item=item, event_type="gift_received", message=f"You received {item.title} (simulated gift).")
        return Response({**GiftEventSerializer(event).data, "message": "Gift preview recorded. No NSAT was transferred."}, status=status.HTTP_201_CREATED)


class CreatorDashboardAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        items = DigitalItem.objects.filter(creator=request.user).select_related("creator", "creator__profile", "creator__creator_profile")
        gifts = GiftEvent.objects.filter(recipient=request.user).select_related("item")[:100]
        notifications = CreatorNotification.objects.filter(recipient=request.user).values("id", "event_type", "message", "is_read", "created_at")[:100]
        creator_profile = CreatorProfile.objects.filter(user=request.user).first() or CreatorProfile(user=request.user)
        sales = CreatorSale.objects.filter(creator=request.user).select_related("item", "order")[:50]
        totals = CreatorSale.objects.filter(creator=request.user).aggregate(
            count=Count("id"), gross=Coalesce(Sum("gross_nsat"), 0), proceeds=Coalesce(Sum("creator_proceeds_nsat"), 0)
        )
        return Response({
            "profile": CreatorProfileSerializer(creator_profile).data,
            "items": DigitalItemSerializer(items, many=True, context={"request": request}).data,
            "gift_activity": GiftEventSerializer(gifts, many=True).data,
            "notifications": list(notifications),
            "sales": [
                {
                    "id": sale.pk,
                    "item": sale.item.title,
                    "gross_nsat": sale.gross_nsat,
                    "platform_fee_nsat": sale.platform_fee_nsat,
                    "creator_proceeds_nsat": sale.creator_proceeds_nsat,
                    "tx_hash": sale.tx_hash,
                    "created_at": sale.created_at.isoformat(),
                }
                for sale in sales
            ],
            "sales_totals": {"count": totals["count"], "gross_nsat": totals["gross"], "creator_proceeds_nsat": totals["proceeds"]},
            "simulated_only": True,
        })

    def patch(self, request):
        creator_profile, _ = CreatorProfile.objects.get_or_create(user=request.user)
        serializer = CreatorProfileSerializer(creator_profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        MarketplaceAuditEvent.objects.create(actor=request.user, action="creator.profile_updated")
        return Response(serializer.data)


class CreatorDirectoryAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        profiles = CreatorProfile.objects.filter(is_public=True, user__marketplace_items__state=DigitalItem.State.APPROVED).select_related("user", "user__profile", "user__creator_profile").distinct()
        rows = []
        for profile in profiles:
            items = DigitalItem.objects.filter(creator=profile.user, state=DigitalItem.State.APPROVED)
            try:
                account_profile = profile.user.profile
            except AttributeError:
                account_profile = None
            rows.append({
                "user_id": profile.user_id,
                "display_name": profile.display_name or getattr(account_profile, "display_name", "") or "SatoshiCore creator",
                "bio": profile.bio or getattr(account_profile, "about", ""),
                "approved_items": DigitalItemSerializer(items, many=True, context={"request": request}).data,
            })
        return Response(rows)


class PurchaseDisputeAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "marketplace_report"

    def post(self, request, purchase_id):
        purchase = get_object_or_404(SimulatedPurchase, pk=purchase_id, buyer=request.user)
        reason = str(request.data.get("reason", "")).strip()[:500]
        if len(reason) < 5:
            raise ValidationError({"reason": "Explain the issue in at least 5 characters."})
        dispute, created = PurchaseDispute.objects.get_or_create(purchase=purchase, defaults={"buyer": request.user, "reason": reason})
        if created:
            MarketplaceAuditEvent.objects.create(actor=request.user, item=purchase.item, action="purchase.dispute_simulated", metadata={"purchase_id": str(purchase.pk)})
        return Response({"id": dispute.pk, "state": dispute.state, "simulation_only": True}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ReportItemAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "marketplace_report"

    def post(self, request, pk):
        item = get_object_or_404(DigitalItem, pk=pk, state=DigitalItem.State.APPROVED)
        serializer = ItemReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = serializer.save(reporter=request.user, item=item)
        MarketplaceAuditEvent.objects.create(actor=request.user, item=item, action="item.reported", metadata={"report_id": report.pk, "reason": report.reason})
        return Response({"id": report.pk, "state": report.state}, status=status.HTTP_201_CREATED)


def _order_or_404(request, order_id):
    return get_object_or_404(
        MarketplaceOrder.objects.select_related("item", "item__creator", "buyer").prefetch_related("payments"),
        pk=order_id,
        buyer=request.user,
    )


def _error_response(error):
    return Response({"code": error.code}, status=error.status)


def _validated_key(request):
    try:
        return uuid.UUID(str(request.data.get("idempotency_key", "")))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError({"idempotency_key": "Provide a UUID idempotency key."})


class OrderCreateAPIView(APIView):
    """Price a listing and open the signed transfers the buyer must pay."""

    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "marketplace_purchase"

    def post(self, request, pk):
        item = get_object_or_404(DigitalItem.objects.select_related("creator"), pk=pk)
        key = _validated_key(request)
        try:
            order = services.create_order(buyer=request.user, item=item, idempotency_key=key)
        except services.MarketplaceError as error:
            return _error_response(error)
        order = MarketplaceOrder.objects.select_related("item").prefetch_related("payments").get(pk=order.pk)
        return Response(services.order_payload(order), status=status.HTTP_201_CREATED)


class OrderListAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        orders = (
            MarketplaceOrder.objects.filter(buyer=request.user)
            .select_related("item")
            .prefetch_related("payments")[:50]
        )
        return Response({"results": [services.order_payload(order) for order in orders]})


class OrderDetailAPIView(APIView):
    """Read an order and pull fresh confirmation state from the indexer."""

    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "marketplace_order"

    def get(self, request, order_id):
        order = _order_or_404(request, order_id)
        order = services.sync_order(order)
        order = MarketplaceOrder.objects.select_related("item").prefetch_related("payments").get(pk=order.pk)
        return Response(services.order_payload(order))


class OrderPaymentAPIView(APIView):
    """Accept one signed tranche, then wait for indexer confirmation."""

    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "marketplace_purchase"

    def post(self, request, order_id, role):
        order = _order_or_404(request, order_id)
        envelope = request.data.get("envelope_xdr") if isinstance(request.data, dict) else None
        try:
            services.record_order_payment(order=order, role=role, envelope=envelope)
        except services.MarketplaceError as error:
            return _error_response(error)
        order = MarketplaceOrder.objects.select_related("item").prefetch_related("payments").get(pk=order.pk)
        return Response(services.order_payload(services.sync_order(order)), status=status.HTTP_200_OK)


class EntitlementListAPIView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = EntitlementSerializer

    def get_queryset(self):
        # Revoked grants stay in the database as an audit record; they are not
        # listed as owned content.
        return MarketplaceEntitlement.objects.filter(owner=self.request.user, revoked_at__isnull=True).select_related(
            "item", "item__creator", "item__creator__creator_profile", "item__creator__nsat_wallet_link"
        )
