import uuid

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import CreatorNotification, CreatorProfile, DigitalItem, GiftEvent, InventoryItem, ItemReport, MarketplaceAuditEvent, PurchaseDispute, SimulatedPurchase
from .serializers import CreatorProfileSerializer, DigitalItemSerializer, GiftEventSerializer, InventorySerializer, ItemReportSerializer, SimulatedPurchaseSerializer, SubmitItemSerializer


class CatalogAPIView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = DigitalItemSerializer

    def get_queryset(self):
        qs = DigitalItem.objects.filter(state=DigitalItem.State.APPROVED).select_related("creator", "creator__profile", "creator__creator_profile")
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


class PurchaseHistoryAPIView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = SimulatedPurchaseSerializer

    def get_queryset(self):
        return SimulatedPurchase.objects.filter(buyer=self.request.user).select_related("item", "item__creator", "item__creator__profile", "item__creator__creator_profile")


class PurchaseSimulationAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "marketplace_purchase"

    def post(self, request, pk):
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
        return Response({
            "profile": CreatorProfileSerializer(creator_profile).data,
            "items": DigitalItemSerializer(items, many=True, context={"request": request}).data,
            "gift_activity": GiftEventSerializer(gifts, many=True).data,
            "notifications": list(notifications),
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
