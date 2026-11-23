import uuid
from io import BytesIO
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import RequestFactory
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from .admin import DigitalItemAdmin
from .models import CreatorProfile, DigitalItem, DigitalItemAsset, GiftEvent, InventoryItem, MarketplaceAuditEvent, SimulatedPurchase


def png_upload(name="sticker.png"):
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGBA", (8, 8), (20, 180, 90, 255)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class MarketplaceAPITests(APITestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(phone_number="+66839935531", password="StrongPassword123")
        self.creator = User.objects.create_user(phone_number="+66839935532", password="StrongPassword123")
        self.item = DigitalItem.objects.create(
            creator=self.creator,
            kind=DigitalItem.Kind.STICKER_PACK,
            title="Test pack",
            proposed_price_nsat=250,
            state=DigitalItem.State.APPROVED,
        )
        self.client.force_authenticate(self.buyer)

    def test_catalog_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(reverse("marketplace:catalog")).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_pending_items_are_not_public(self):
        pending = DigitalItem.objects.create(creator=self.creator, kind=DigitalItem.Kind.BADGE, title="Hidden", state=DigitalItem.State.PENDING)
        response = self.client.get(reverse("marketplace:catalog"))
        returned_ids = {row["id"] for row in response.data}
        self.assertIn(self.item.pk, returned_ids)
        self.assertNotIn(pending.pk, returned_ids)

    def test_catalog_uses_marketplace_creator_profile_name(self):
        CreatorProfile.objects.create(user=self.creator, display_name="Studio Name")
        response = self.client.get(reverse("marketplace:catalog"))
        row = next(item for item in response.data if item["id"] == self.item.pk)
        self.assertEqual(row["creator_name"], "Studio Name")

    def test_purchase_is_simulated_idempotent_and_grants_user_owned_inventory(self):
        key = str(uuid.uuid4())
        url = reverse("marketplace:purchase-simulation", args=(self.item.pk,))
        first = self.client.post(url, {"idempotency_key": key}, format="json")
        second = self.client.post(url, {"idempotency_key": key}, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertTrue(first.data["simulation_only"])
        self.assertFalse(first.data["on_chain"])
        self.assertEqual(SimulatedPurchase.objects.filter(buyer=self.buyer).count(), 1)
        self.assertEqual(InventoryItem.objects.filter(owner=self.buyer, item=self.item).count(), 1)
        self.assertEqual(MarketplaceAuditEvent.objects.filter(action="purchase.simulated").count(), 1)

    def test_purchase_cannot_access_unapproved_listing(self):
        pending = DigitalItem.objects.create(creator=self.creator, kind=DigitalItem.Kind.BADGE, title="Hidden", state=DigitalItem.State.PENDING)
        response = self.client.post(reverse("marketplace:purchase-simulation", args=(pending.pk,)), {"idempotency_key": str(uuid.uuid4())}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_idempotency_key_cannot_be_reused_for_another_item(self):
        other = DigitalItem.objects.create(creator=self.creator, kind=DigitalItem.Kind.BADGE, title="Another", state=DigitalItem.State.APPROVED)
        key = str(uuid.uuid4())
        self.client.post(reverse("marketplace:purchase-simulation", args=(self.item.pk,)), {"idempotency_key": key}, format="json")
        response = self.client.post(reverse("marketplace:purchase-simulation", args=(other.pk,)), {"idempotency_key": key}, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_concurrent_idempotency_key_collision_for_another_item_returns_conflict(self):
        other = DigitalItem.objects.create(creator=self.creator, kind=DigitalItem.Kind.BADGE, title="Another", state=DigitalItem.State.APPROVED)
        key = uuid.uuid4()
        SimulatedPurchase.objects.create(buyer=self.buyer, item=self.item, idempotency_key=key, amount_nsat=250)
        with patch.object(SimulatedPurchase.objects, "create", side_effect=IntegrityError("unique collision")):
            response = self.client.post(reverse("marketplace:purchase-simulation", args=(other.pk,)), {"idempotency_key": str(key)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_dispute_is_private_to_the_purchase_owner_and_simulated(self):
        purchase = SimulatedPurchase.objects.create(buyer=self.buyer, item=self.item, idempotency_key=uuid.uuid4(), amount_nsat=250)
        url = reverse("marketplace:purchase-dispute", args=(purchase.pk,))
        other_client_user = User.objects.create_user(phone_number="+66839935533", password="StrongPassword123")
        self.client.force_authenticate(other_client_user)
        self.assertEqual(self.client.post(url, {"reason": "Not my purchase"}, format="json").status_code, status.HTTP_404_NOT_FOUND)
        self.client.force_authenticate(self.buyer)
        response = self.client.post(url, {"reason": "Wrong preview content"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["simulation_only"])

    def test_creator_submission_requires_moderation(self):
        response = self.client.post(reverse("marketplace:submit"), {"kind": "theme", "title": "My theme", "proposed_price_nsat": 45}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item = DigitalItem.objects.get(pk=response.data["id"])
        self.assertEqual(item.creator, self.buyer)
        self.assertEqual(item.state, DigitalItem.State.PENDING)

    def test_sticker_pack_submission_stores_uploaded_assets_pending_review(self):
        response = self.client.post(
            reverse("marketplace:submit"),
            {"kind": "sticker_pack", "title": "Creator pack", "assets": [png_upload()]},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        item = DigitalItem.objects.get(pk=response.data["id"])
        self.assertEqual(item.state, DigitalItem.State.PENDING)
        self.assertEqual(item.assets.count(), 1)

    def test_sticker_pack_requires_at_least_one_asset(self):
        response = self.client.post(
            reverse("marketplace:submit"),
            {"kind": "sticker_pack", "title": "Empty pack"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(DigitalItem.objects.filter(title="Empty pack").exists())

    def test_only_inventory_owner_can_load_full_approved_sticker_assets(self):
        asset = DigitalItemAsset.objects.create(item=self.item, image=png_upload(), position=0)
        url = reverse("marketplace:owned-stickers")
        self.assertEqual(self.client.get(url).data, [])

        self.client.post(
            reverse("marketplace:purchase-simulation", args=(self.item.pk,)),
            {"idempotency_key": str(uuid.uuid4())}, format="json",
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["stickers"][0]["id"], asset.pk)
        self.assertTrue(response.data[0]["stickers"][0]["file"].endswith(asset.image.url))

        self.client.force_authenticate(self.creator)
        self.assertEqual(self.client.get(url).data, [])

    def test_gift_history_is_limited_to_the_authenticated_user(self):
        gift = DigitalItem.objects.create(creator=self.creator, kind=DigitalItem.Kind.GIFT, title="Heart", state=DigitalItem.State.APPROVED)
        GiftEvent.objects.create(sender=self.buyer, recipient=self.creator, item=gift)
        response = self.client.get(reverse("marketplace:gifts"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["sent"]), 1)
        self.assertEqual(response.data["sent"][0]["item"]["title"], "Heart")
        self.assertEqual(response.data["received"], [])

    def test_admin_approval_keeps_audit_event_for_state_filtered_queryset(self):
        item = DigitalItem.objects.create(creator=self.creator, kind=DigitalItem.Kind.BADGE, title="Pending", state=DigitalItem.State.PENDING)
        request = RequestFactory().post("/admin/marketplace/digitalitem/")
        request.user = self.buyer
        queryset = DigitalItem.objects.filter(pk=item.pk, state=DigitalItem.State.PENDING)
        DigitalItemAdmin(DigitalItem, AdminSite()).approve_items(request, queryset)
        item.refresh_from_db()
        self.assertEqual(item.state, DigitalItem.State.APPROVED)
        self.assertTrue(MarketplaceAuditEvent.objects.filter(item=item, action="item.approved").exists())
