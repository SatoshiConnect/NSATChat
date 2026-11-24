import os
import tempfile
import threading
import uuid
from datetime import timedelta
from io import BytesIO, StringIO
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.db import connection
from django.test import RequestFactory, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from .admin import DigitalItemAdmin
from apps.wallet_integration.models import WalletLink
from apps.wallet_integration.tests.test_read import SIGNED_PAYMENT_VECTOR, VALID_DESTINATION, VALID_SOURCE
from apps.wallet_integration.views import _encode_wallet_address
from . import services
from . import reconciliation
from .models import (
    CreatorNotification,
    CreatorProfile,
    CreatorSale,
    DigitalItem,
    DigitalItemAsset,
    GiftEvent,
    InventoryItem,
    MarketplaceAuditEvent,
    MarketplaceEntitlement,
    MarketplaceOrder,
    MarketplaceReconciliationIssue,
    MarketplaceReconciliationRun,
    OrderPayment,
    SimulatedPurchase,
)


def png_upload(name="sticker.png"):
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGBA", (8, 8), (20, 180, 90, 255)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


SIMULATION_ON = override_settings(MARKETPLACE_ALLOW_SIMULATED_PURCHASES=True)


@SIMULATION_ON
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


def _new_address():
    import os

    return _encode_wallet_address(os.urandom(32))


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}},
    MARKETPLACE_LIVE_PAYMENTS=True,
    MARKETPLACE_ALLOW_SIMULATED_PURCHASES=False,
    MARKETPLACE_PLATFORM_FEE_BPS=0,
    MARKETPLACE_TREASURY_ADDRESS="",
)
class OrderSettlementTests(APITestCase):
    """The paid path: priced in NSAT, verified per tranche, fulfilled on confirmation."""

    def setUp(self):
        self.buyer = User.objects.create_user(phone_number="+66839935541", password="StrongPassword123")
        self.creator = User.objects.create_user(phone_number="+66839935542", password="StrongPassword123")
        WalletLink.objects.create(user=self.buyer, address=VALID_SOURCE)
        WalletLink.objects.create(user=self.creator, address=VALID_DESTINATION)
        self.item = DigitalItem.objects.create(
            creator=self.creator,
            kind=DigitalItem.Kind.STICKER_PACK,
            title="Paid pack",
            proposed_price_nsat=123_456_789,
            state=DigitalItem.State.APPROVED,
        )
        DigitalItemAsset.objects.create(item=self.item, image=png_upload(), position=0)
        self.client.force_authenticate(self.buyer)

    def _create_order(self, key=None):
        return self.client.post(
            reverse("marketplace:order-create", args=(self.item.pk,)),
            {"idempotency_key": key or str(uuid.uuid4())},
            format="json",
        )

    def test_order_prices_creator_share_without_platform_fee(self):
        response = self._create_order()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["total_due_nsat"], 123_456_789)
        self.assertEqual(response.data["platform_fee_nsat"], 0)
        self.assertEqual(len(response.data["payments"]), 1)
        payment = response.data["payments"][0]
        self.assertEqual(payment["role"], "creator")
        self.assertEqual(payment["payee_address"], VALID_DESTINATION)
        self.assertEqual(payment["amount_nsat"], 123_456_789)
        self.assertEqual(response.data["state"], "awaiting_payment")

    def test_order_is_idempotent_per_key_and_rejects_a_second_open_order(self):
        key = str(uuid.uuid4())
        first = self._create_order(key)
        replay = self._create_order(key)
        self.assertEqual(first.data["id"], replay.data["id"])
        other = self._create_order()
        self.assertEqual(other.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(other.data["code"], "order_already_open")

    def test_order_requires_linked_wallets_and_a_creator(self):
        WalletLink.objects.filter(user=self.buyer).delete()
        self.assertEqual(self._create_order().data["code"], "wallet_not_linked")
        WalletLink.objects.create(user=self.buyer, address=VALID_SOURCE)
        WalletLink.objects.filter(user=self.creator).delete()
        self.assertEqual(self._create_order().data["code"], "creator_wallet_unavailable")
        WalletLink.objects.create(user=self.creator, address=VALID_DESTINATION)
        self.item.creator = None
        self.item.save(update_fields=["creator"])
        self.assertEqual(self._create_order().status_code, status.HTTP_404_NOT_FOUND)

    def test_creator_cannot_buy_their_own_listing(self):
        self.client.force_authenticate(self.creator)
        self.assertEqual(self._create_order().data["code"], "cannot_buy_own_item")

    def test_platform_fee_needs_a_treasury_or_the_sale_is_refused(self):
        with override_settings(MARKETPLACE_PLATFORM_FEE_BPS=500):
            response = self._create_order()
            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(response.data["code"], "marketplace_misconfigured")
        treasury = _new_address()
        with override_settings(MARKETPLACE_PLATFORM_FEE_BPS=500, MARKETPLACE_TREASURY_ADDRESS=treasury):
            response = self._create_order()
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(response.data["platform_fee_nsat"], 6_172_839)
            self.assertEqual(response.data["creator_proceeds_nsat"], 117_283_950)
            roles = {payment["role"]: payment for payment in response.data["payments"]}
            self.assertEqual(roles["platform"]["payee_address"], treasury)
            self.assertEqual(
                roles["creator"]["amount_nsat"] + roles["platform"]["amount_nsat"],
                response.data["unit_amount_nsat"],
            )

    def test_split_is_integer_exact(self):
        self.assertEqual(services.split_amounts(1000, 250), (25, 975))
        self.assertEqual(services.split_amounts(1, 5000), (0, 1))
        self.assertEqual(services.split_amounts(2**63 - 1, 0), (0, 2**63 - 1))
        with self.assertRaises(services.MarketplaceError):
            services.split_amounts(2**63 - 1, 10000)
        with self.assertRaises(services.MarketplaceError):
            services.split_amounts(0, 0)

    def test_signed_envelope_is_recorded_with_its_on_chain_hash(self):
        order = self._create_order().data
        url = reverse("marketplace:order-payment", args=(order["id"], "creator"))
        with patch("apps.marketplace.services.submit_signed_envelope") as submit:
            submit.return_value = "PENDING"
            wrong_amount = self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        self.assertEqual(wrong_amount.status_code, status.HTTP_200_OK)
        self.assertEqual(wrong_amount.data["payments"][0]["state"], "pending")
        self.assertEqual(
            wrong_amount.data["payments"][0]["tx_hash"],
            "ed416812815ee2993c26ca65ca7e14f8d81f0b0e36ad7aec8b0c32ca0e11b6d7",
        )
        replay = self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        self.assertEqual(replay.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(replay.data["code"], "payment_already_submitted")

    def test_mismatched_envelope_is_refused_before_the_gateway(self):
        mismatched = DigitalItem.objects.create(
            creator=self.creator,
            kind=DigitalItem.Kind.BADGE,
            title="Different price",
            proposed_price_nsat=5,
            state=DigitalItem.State.APPROVED,
        )
        order = self.client.post(
            reverse("marketplace:order-create", args=(mismatched.pk,)),
            {"idempotency_key": str(uuid.uuid4())},
            format="json",
        ).data
        url = reverse("marketplace:order-payment", args=(order["id"], "creator"))
        with patch("apps.marketplace.services.submit_signed_envelope") as submit:
            response = self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "envelope_amount_mismatch")
        submit.assert_not_called()

        WalletLink.objects.filter(user=self.buyer).update(address=_new_address())
        resp = self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        self.assertEqual(resp.data["code"], "envelope_source_mismatch")

    def test_confirmed_payment_grants_entitlement_and_sale_once(self):
        order = self._create_order().data
        url = reverse("marketplace:order-payment", args=(order["id"], "creator"))
        verdict = {"status": "confirmed", "success": True, "result_code": "", "ledger": 9001}
        with patch("apps.marketplace.services.submit_signed_envelope", return_value="PENDING"), \
                patch("apps.marketplace.services.confirmation_for_hash", return_value=verdict):
            response = self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["state"], "paid")
        self.assertEqual(MarketplaceEntitlement.objects.filter(owner=self.buyer, item=self.item).count(), 1)
        self.assertEqual(CreatorSale.objects.filter(creator=self.creator).count(), 1)
        self.assertEqual(CreatorSale.objects.get().creator_proceeds_nsat, 123_456_789)
        self.assertTrue(MarketplaceAuditEvent.objects.filter(action="order.paid").exists())
        self.assertTrue(
            self.creator.creator_notifications.filter(event_type="sale").exists()
            if hasattr(self.creator, "creator_notifications")
            else True
        )

        detail = reverse("marketplace:order-detail", args=(order["id"],))
        self.assertEqual(self.client.get(detail).data["state"], "paid")
        with patch("apps.marketplace.services.submit_signed_envelope", return_value="PENDING"):
            again = self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        self.assertEqual(again.status_code, status.HTTP_200_OK)
        self.assertEqual(MarketplaceEntitlement.objects.filter(owner=self.buyer).count(), 1)
        self.assertEqual(CreatorSale.objects.count(), 1)

    def test_pending_confirmation_keeps_the_order_open_without_granting_access(self):
        order = self._create_order().data
        url = reverse("marketplace:order-payment", args=(order["id"], "creator"))
        pending = {"status": "pending", "success": None, "result_code": "", "ledger": None}
        with patch("apps.marketplace.services.submit_signed_envelope", return_value="PENDING"), \
                patch("apps.marketplace.services.confirmation_for_hash", return_value=pending):
            response = self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        self.assertEqual(response.data["state"], "partially_paid")
        self.assertFalse(MarketplaceEntitlement.objects.exists())
        self.assertEqual(self.client.get(reverse("marketplace:owned-stickers")).data, [])

    def test_failed_confirmation_closes_the_order(self):
        order = self._create_order().data
        url = reverse("marketplace:order-payment", args=(order["id"], "creator"))
        failed = {"status": "failed", "success": False, "result_code": "tx_failed", "ledger": None}
        with patch("apps.marketplace.services.submit_signed_envelope", return_value="PENDING"), \
                patch("apps.marketplace.services.confirmation_for_hash", return_value=failed):
            response = self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        self.assertEqual(response.data["state"], "failed")
        self.assertFalse(MarketplaceEntitlement.objects.exists())

    def test_an_owned_item_cannot_be_paid_for_twice(self):
        order = self._create_order().data
        url = reverse("marketplace:order-payment", args=(order["id"], "creator"))
        verdict = {"status": "confirmed", "success": True, "result_code": "", "ledger": 7}
        with patch("apps.marketplace.services.submit_signed_envelope", return_value="PENDING"), \
                patch("apps.marketplace.services.confirmation_for_hash", return_value=verdict):
            self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        response = self._create_order()
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "already_owned")
        row = next(entry for entry in self.client.get(reverse("marketplace:catalog")).data if entry["id"] == self.item.pk)
        self.assertEqual(row["purchase_mode"], "owned")

    def _pay(self, order, ledger=21):
        url = reverse("marketplace:order-payment", args=(order["id"], "creator"))
        verdict = {"status": "confirmed", "success": True, "result_code": "", "ledger": ledger}
        with patch("apps.marketplace.services.submit_signed_envelope", return_value="PENDING"), \
                patch("apps.marketplace.services.confirmation_for_hash", return_value=verdict):
            return self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")

    def test_paid_access_survives_listing_disable_until_revoked(self):
        order = self._create_order().data
        self.assertEqual(self._pay(order).data["state"], "paid")
        DigitalItem.objects.filter(pk=self.item.pk).update(state=DigitalItem.State.DISABLED)

        # The buyer keeps what they paid for, and the listing stops new sales.
        library = self.client.get(reverse("marketplace:owned-stickers"))
        self.assertEqual([row["id"] for row in library.data], [self.item.pk])
        self.assertEqual(len(self.client.get(reverse("marketplace:entitlements")).data), 1)

        newcomer = User.objects.create_user(phone_number="+66839935561", password="StrongPassword123")
        WalletLink.objects.create(user=newcomer, address=_new_address())
        self.client.force_authenticate(newcomer)
        self.assertEqual(self._create_order().status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(self.buyer)
        entitlement = MarketplaceEntitlement.objects.get()
        services.revoke_entitlement(entitlement, reason="Copyright claim upheld")
        self.assertEqual(self.client.get(reverse("marketplace:owned-stickers")).data, [])
        self.assertEqual(self.client.get(reverse("marketplace:entitlements")).data, [])
        entitlement.refresh_from_db()
        self.assertIsNotNone(entitlement.revoked_at)
        self.assertEqual(entitlement.revoked_reason, "Copyright claim upheld")
        self.assertTrue(MarketplaceAuditEvent.objects.filter(action="entitlement.revoked").exists())
        self.assertTrue(
            CreatorNotification.objects.filter(recipient=self.buyer, event_type="entitlement_revoked").exists()
        )

    def test_mistaken_revocation_can_be_restored_with_audit(self):
        order = self._create_order().data
        self._pay(order, ledger=23)
        entitlement = MarketplaceEntitlement.objects.get()
        services.revoke_entitlement(entitlement, reason="Wrong takedown")
        self.assertEqual(self.client.get(reverse("marketplace:owned-stickers")).data, [])

        services.restore_entitlement(entitlement, reason="Appeal accepted")
        entitlement.refresh_from_db()
        self.assertIsNone(entitlement.revoked_at)
        self.assertEqual(entitlement.revoked_reason, "")
        self.assertIsNone(entitlement.revoked_by)
        self.assertEqual(len(self.client.get(reverse("marketplace:owned-stickers")).data), 1)
        self.assertEqual(len(self.client.get(reverse("marketplace:entitlements")).data), 1)
        self.assertTrue(MarketplaceAuditEvent.objects.filter(action="entitlement.restored").exists())
        self.assertTrue(
            CreatorNotification.objects.filter(recipient=self.buyer, event_type="entitlement_restored").exists()
        )
        # Restoring an active grant is a no-op and must not duplicate audit rows.
        services.restore_entitlement(entitlement)
        self.assertEqual(MarketplaceAuditEvent.objects.filter(action="entitlement.restored").count(), 1)

    def test_reusing_a_signed_transfer_on_another_order_returns_409(self):
        second_item = DigitalItem.objects.create(
            creator=self.creator,
            kind=DigitalItem.Kind.STICKER_PACK,
            title="Second pack",
            proposed_price_nsat=123_456_789,
            state=DigitalItem.State.APPROVED,
        )
        first_order = self._create_order().data
        second_order = self.client.post(
            reverse("marketplace:order-create", args=(second_item.pk,)),
            {"idempotency_key": str(uuid.uuid4())},
            format="json",
        ).data
        verdict = {"status": "pending", "success": None, "result_code": "", "ledger": None}
        with patch("apps.marketplace.services.submit_signed_envelope", return_value="PENDING"), \
                patch("apps.marketplace.services.confirmation_for_hash", return_value=verdict):
            first = self.client.post(
                reverse("marketplace:order-payment", args=(first_order["id"], "creator")),
                {"envelope_xdr": SIGNED_PAYMENT_VECTOR},
                format="json",
            )
            reused = self.client.post(
                reverse("marketplace:order-payment", args=(second_order["id"], "creator")),
                {"envelope_xdr": SIGNED_PAYMENT_VECTOR},
                format="json",
            )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(reused.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(reused.data["code"], "payment_already_used")
        self.assertEqual(OrderPayment.objects.filter(tx_hash="ed416812815ee2993c26ca65ca7e14f8d81f0b0e36ad7aec8b0c32ca0e11b6d7").count(), 1)
        self.assertEqual(MarketplaceOrder.objects.get(pk=second_order["id"]).state, "awaiting_payment")

    def test_racing_unique_violation_is_reported_as_409(self):
        """Simulate the loser of an in-flight race: the row exists but the pre-check missed it."""
        second_item = DigitalItem.objects.create(
            creator=self.creator,
            kind=DigitalItem.Kind.STICKER_PACK,
            title="Racing pack",
            proposed_price_nsat=123_456_789,
            state=DigitalItem.State.APPROVED,
        )
        first_order = self._create_order().data
        second_order = self.client.post(
            reverse("marketplace:order-create", args=(second_item.pk,)),
            {"idempotency_key": str(uuid.uuid4())},
            format="json",
        ).data
        # The winner already committed this signature on the first order.
        OrderPayment.objects.filter(order_id=first_order["id"], role="creator").update(
            tx_hash="ed416812815ee2993c26ca65ca7e14f8d81f0b0e36ad7aec8b0c32ca0e11b6d7",
            submitted_at=1,
        )
        with patch("apps.marketplace.services._hash_used_by_another_order", return_value=False), \
                patch("apps.marketplace.services.submit_signed_envelope", return_value="PENDING"), \
                patch("apps.marketplace.services.confirmation_for_hash", return_value={"status": "pending", "success": None, "result_code": "", "ledger": None}):
            response = self.client.post(
                reverse("marketplace:order-payment", args=(second_order["id"], "creator")),
                {"envelope_xdr": SIGNED_PAYMENT_VECTOR},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "payment_already_used")

    def _subscribe_buyer_inbox(self):
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        channel = async_to_sync(layer.new_channel)()
        async_to_sync(layer.group_add)(f"chat_inbox_{self.buyer.pk}", channel)
        return layer, channel

    @staticmethod
    def _channel_is_empty(layer, channel):
        import asyncio

        from asgiref.sync import async_to_sync

        async def silent():
            try:
                await asyncio.wait_for(layer.receive(channel), timeout=0.2)
                return False
            except asyncio.TimeoutError:
                return True

        return async_to_sync(silent)()

    def test_buyer_gets_a_realtime_unlock_event_only_once(self):
        from asgiref.sync import async_to_sync

        layer, channel = self._subscribe_buyer_inbox()
        order = self._create_order().data
        self._pay(order, ledger=51)
        event = async_to_sync(layer.receive)(channel)
        self.assertEqual(event["type"], "inbox.marketplace_paid")
        self.assertEqual(event["order_id"], order["id"])
        self.assertEqual(event["item_id"], self.item.pk)
        self.assertEqual(event["item_title"], "Paid pack")

        # Polling an already-paid order must not re-announce the unlock.
        self.client.get(reverse("marketplace:order-detail", args=(order["id"],)))
        self.assertTrue(self._channel_is_empty(layer, channel))

    def test_inbox_consumer_forwards_the_unlock_event(self):
        import json as jsonlib

        from asgiref.sync import async_to_sync

        from apps.chat.consumers import ChatInboxConsumer

        consumer = ChatInboxConsumer()
        sent = []

        async def fake_send(text_data=None, close=False):
            sent.append(text_data)

        consumer.send = fake_send
        async_to_sync(consumer.inbox_marketplace_paid)({
            "type": "inbox.marketplace_paid",
            "order_id": "order-1",
            "item_id": 9,
            "item_title": "Paid pack",
        })
        payload = jsonlib.loads(sent[0])
        self.assertEqual(payload, {
            "type": "marketplace.order_paid",
            "order_id": "order-1",
            "item_id": 9,
            "item_title": "Paid pack",
        })

    def _entitlement_admin_request(self, user):
        from django.contrib.messages.storage.cookie import CookieStorage

        request = RequestFactory().post("/admin/marketplace/marketplaceentitlement/")
        request.user = user
        setattr(request, "_messages", CookieStorage(request))
        return request

    def test_admin_revoke_action_removes_access_audits_and_notifies(self):
        from django.contrib.admin.sites import AdminSite

        from .admin import MarketplaceEntitlementAdmin

        order = self._create_order().data
        self._pay(order, ledger=31)
        admin_user = User.objects.create_user(phone_number="+66839935581", password="StrongPassword123")
        request = self._entitlement_admin_request(admin_user)
        model_admin = MarketplaceEntitlementAdmin(MarketplaceEntitlement, AdminSite())

        model_admin.revoke_entitlements(request, MarketplaceEntitlement.objects.all())

        entitlement = MarketplaceEntitlement.objects.get()
        self.assertIsNotNone(entitlement.revoked_at)
        self.assertEqual(entitlement.revoked_reason, "Revoked by moderator")
        self.assertEqual(entitlement.revoked_by, admin_user)
        self.assertEqual(self.client.get(reverse("marketplace:owned-stickers")).data, [])
        self.assertTrue(
            MarketplaceAuditEvent.objects.filter(
                action="entitlement.revoked", metadata__reason="Revoked by moderator"
            ).exists()
        )
        self.assertTrue(
            CreatorNotification.objects.filter(recipient=self.buyer, event_type="entitlement_revoked").exists()
        )
        self.assertEqual(len(list(request._messages)), 1)

        # Re-running the action must not re-revoke or duplicate audit rows.
        model_admin.revoke_entitlements(request, MarketplaceEntitlement.objects.all())
        self.assertEqual(MarketplaceAuditEvent.objects.filter(action="entitlement.revoked").count(), 1)
        self.assertEqual(len(list(request._messages)), 2)

    def test_admin_restore_action_returns_access_after_a_mistake(self):
        from django.contrib.admin.sites import AdminSite

        from .admin import MarketplaceEntitlementAdmin

        order = self._create_order().data
        self._pay(order, ledger=32)
        admin_user = User.objects.create_user(phone_number="+66839935582", password="StrongPassword123")
        model_admin = MarketplaceEntitlementAdmin(MarketplaceEntitlement, AdminSite())
        services.revoke_entitlement(MarketplaceEntitlement.objects.get(), actor=admin_user, reason="Wrong takedown")
        self.assertEqual(self.client.get(reverse("marketplace:owned-stickers")).data, [])

        request = self._entitlement_admin_request(admin_user)
        model_admin.restore_entitlements(request, MarketplaceEntitlement.objects.all())

        entitlement = MarketplaceEntitlement.objects.get()
        self.assertIsNone(entitlement.revoked_at)
        self.assertEqual(entitlement.revoked_reason, "")
        self.assertIsNone(entitlement.revoked_by)
        self.assertEqual(len(self.client.get(reverse("marketplace:owned-stickers")).data), 1)
        audit = MarketplaceAuditEvent.objects.get(action="entitlement.restored")
        self.assertEqual(audit.actor, admin_user)
        self.assertEqual(audit.metadata["previous_reason"], "Wrong takedown")
        self.assertTrue(
            CreatorNotification.objects.filter(recipient=self.buyer, event_type="entitlement_restored").exists()
        )
        self.assertEqual(len(list(request._messages)), 1)

        # Nothing is revoked any more, so a second run changes nothing.
        model_admin.restore_entitlements(request, MarketplaceEntitlement.objects.all())
        self.assertEqual(MarketplaceAuditEvent.objects.filter(action="entitlement.restored").count(), 1)

    def test_creator_sale_survives_buyer_account_deletion(self):
        order = self._create_order().data
        self._pay(order, ledger=22)
        sale = CreatorSale.objects.get()
        reference = sale.order_reference
        proceeds = sale.creator_proceeds_nsat
        self.assertEqual(str(reference), order["id"])
        self.assertEqual(len(sale.buyer_reference), 32)

        self.buyer.delete()

        sale = CreatorSale.objects.get()
        self.assertIsNone(sale.order)
        self.assertEqual(sale.order_reference, reference)
        self.assertEqual(sale.creator_proceeds_nsat, proceeds)
        self.assertFalse(MarketplaceOrder.objects.exists())
        self.assertFalse(MarketplaceEntitlement.objects.exists())

        self.client.force_authenticate(self.creator)
        dashboard = self.client.get(reverse("marketplace:creator-dashboard")).data
        self.assertEqual(dashboard["sales_totals"]["count"], 1)
        self.assertEqual(dashboard["sales_totals"]["creator_proceeds_nsat"], proceeds)
        self.assertEqual(dashboard["sales"][0]["item"], "Paid pack")

    def test_entitlement_unlocks_the_sticker_pack_once_paid(self):
        order = self._create_order().data
        url = reverse("marketplace:order-payment", args=(order["id"], "creator"))
        verdict = {"status": "confirmed", "success": True, "result_code": "", "ledger": 5}
        with patch("apps.marketplace.services.submit_signed_envelope", return_value="PENDING"), \
                patch("apps.marketplace.services.confirmation_for_hash", return_value=verdict):
            self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        library = self.client.get(reverse("marketplace:owned-stickers"))
        self.assertEqual(len(library.data), 1)
        self.assertEqual(library.data[0]["id"], self.item.pk)
        entitlements = self.client.get(reverse("marketplace:entitlements"))
        self.assertEqual(len(entitlements.data), 1)
        self.assertEqual(entitlements.data[0]["item"]["id"], self.item.pk)

    def test_creator_dashboard_reports_confirmed_sales(self):
        order = self._create_order().data
        url = reverse("marketplace:order-payment", args=(order["id"], "creator"))
        verdict = {"status": "confirmed", "success": True, "result_code": "", "ledger": 11}
        with patch("apps.marketplace.services.submit_signed_envelope", return_value="PENDING"), \
                patch("apps.marketplace.services.confirmation_for_hash", return_value=verdict):
            self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        self.client.force_authenticate(self.creator)
        dashboard = self.client.get(reverse("marketplace:creator-dashboard")).data
        self.assertEqual(dashboard["sales_totals"]["count"], 1)
        self.assertEqual(dashboard["sales_totals"]["creator_proceeds_nsat"], 123_456_789)
        self.assertEqual(dashboard["sales"][0]["item"], "Paid pack")

    def test_reconciliation_command_fulfils_a_payment_after_the_buyer_leaves(self):
        from django.core.management import call_command

        order = self._create_order().data
        url = reverse("marketplace:order-payment", args=(order["id"], "creator"))
        pending = {"status": "pending", "success": None, "result_code": "", "ledger": None}
        with patch("apps.marketplace.services.submit_signed_envelope", return_value="PENDING"), \
                patch("apps.marketplace.services.confirmation_for_hash", return_value=pending):
            self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        self.assertFalse(MarketplaceEntitlement.objects.exists())
        confirmed = {"status": "confirmed", "success": True, "result_code": "", "ledger": 12}
        with patch("apps.marketplace.services.confirmation_for_hash", return_value=confirmed):
            call_command("settle_marketplace_orders", stdout=StringIO())
        self.assertEqual(MarketplaceOrder.objects.get(pk=order["id"]).state, "paid")
        self.assertEqual(MarketplaceEntitlement.objects.filter(owner=self.buyer, item=self.item).count(), 1)
        self.assertEqual(CreatorSale.objects.count(), 1)

    def test_buyer_sees_their_own_orders(self):
        order = self._create_order().data
        listed = self.client.get(reverse("marketplace:order-list")).data["results"]
        self.assertEqual([row["id"] for row in listed], [order["id"]])
        self.assertEqual(listed[0]["item"]["title"], "Paid pack")

    def test_orders_are_private_to_the_buyer(self):
        order = self._create_order().data
        intruder = User.objects.create_user(phone_number="+66839935543", password="StrongPassword123")
        self.client.force_authenticate(intruder)
        detail = reverse("marketplace:order-detail", args=(order["id"],))
        self.assertEqual(self.client.get(detail).status_code, status.HTTP_404_NOT_FOUND)
        url = reverse("marketplace:order-payment", args=(order["id"], "creator"))
        self.assertEqual(self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json").status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get(reverse("marketplace:order-list")).data["results"], [])

    def test_expired_order_refuses_late_payment(self):
        order = self._create_order().data
        MarketplaceOrder.objects.filter(pk=order["id"]).update(expires_at=services.timezone.now() - services.timedelta(seconds=1))
        url = reverse("marketplace:order-payment", args=(order["id"], "creator"))
        with patch("apps.marketplace.services.submit_signed_envelope") as submit:
            response = self.client.post(url, {"envelope_xdr": SIGNED_PAYMENT_VECTOR}, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "order_expired")
        submit.assert_not_called()

    @override_settings(MARKETPLACE_LIVE_PAYMENTS=False)
    def test_orders_and_payments_are_unavailable_while_live_payments_are_off(self):
        response = self._create_order()
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["code"], "marketplace_payments_unavailable")

    def test_simulation_is_disabled_on_the_settlement_path(self):
        key = str(uuid.uuid4())
        response = self.client.post(
            reverse("marketplace:purchase-simulation", args=(self.item.pk,)),
            {"idempotency_key": key},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(SimulatedPurchase.objects.exists())


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}},
    MARKETPLACE_LIVE_PAYMENTS=True,
    MARKETPLACE_ALLOW_SIMULATED_PURCHASES=False,
)
class PublishItemCommandTests(APITestCase):
    """Operators publish real listings; assets and price are validated."""

    def setUp(self):
        self.creator = User.objects.create_user(phone_number="+66839935551", password="StrongPassword123")
        WalletLink.objects.create(user=self.creator, address=VALID_DESTINATION)
        self.folder = tempfile.mkdtemp()
        with open(os.path.join(self.folder, "one.png"), "wb") as handle:
            handle.write(png_upload().read())
        with open(os.path.join(self.folder, "two.png"), "wb") as handle:
            handle.write(png_upload("two.png").read())

    def tearDown(self):
        for name in os.listdir(self.folder):
            os.remove(os.path.join(self.folder, name))
        os.rmdir(self.folder)

    def test_publishes_an_approved_paid_listing_with_its_assets(self):
        from django.core.management import call_command

        call_command(
            "publish_marketplace_item",
            creator=self.creator.phone_number,
            title="Studio pack",
            price=250,
            assets=self.folder,
            approve=True,
            stdout=StringIO(),
        )
        item = DigitalItem.objects.get(title="Studio pack")
        self.assertEqual(item.state, DigitalItem.State.APPROVED)
        self.assertEqual(item.proposed_price_nsat, 250)
        self.assertEqual(item.assets.count(), 2)
        self.assertTrue(MarketplaceAuditEvent.objects.filter(action="item.published", item=item).exists())

        buyer = User.objects.create_user(phone_number="+66839935552", password="StrongPassword123")
        WalletLink.objects.create(user=buyer, address=VALID_SOURCE)
        self.client.force_authenticate(buyer)
        catalog = self.client.get(reverse("marketplace:catalog"))
        row = next(entry for entry in catalog.data if entry["id"] == item.pk)
        self.assertEqual(row["purchase_mode"], "nsat")
        self.assertEqual(row["price_label"], "250 NSAT")

    def test_rejects_a_free_listing(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("publish_marketplace_item", creator=self.creator.phone_number, title="Free", price=0, stdout=StringIO())
        self.assertFalse(DigitalItem.objects.filter(title="Free").exists())


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}},
    MARKETPLACE_LIVE_PAYMENTS=True,
    MARKETPLACE_ALLOW_SIMULATED_PURCHASES=False,
    MARKETPLACE_PLATFORM_FEE_BPS=0,
    MARKETPLACE_TREASURY_ADDRESS="",
)
@skipUnless(
    connection.vendor != "sqlite",
    "SQLite shared-cache returns 'database table is locked' instead of a unique violation; "
    "run this race with DJANGO_SETTINGS_MODULE=config.settings.test_postgres (CI does). "
    "The deterministic 409 tests cover the same paths on every database.",
)
class EnvelopeReuseConcurrencyTests(TransactionTestCase):
    """Two payment requests race on one signature; exactly one may be accepted."""

    def setUp(self):
        self.buyer = User.objects.create_user(phone_number="+66839935571", password="StrongPassword123")
        self.creator = User.objects.create_user(phone_number="+66839935572", password="StrongPassword123")
        WalletLink.objects.create(user=self.buyer, address=VALID_SOURCE)
        WalletLink.objects.create(user=self.creator, address=VALID_DESTINATION)
        self.orders = []
        for index in range(2):
            item = DigitalItem.objects.create(
                creator=self.creator,
                kind=DigitalItem.Kind.STICKER_PACK,
                title=f"Race pack {index}",
                proposed_price_nsat=123_456_789,
                state=DigitalItem.State.APPROVED,
            )
            order = services.create_order(buyer=self.buyer, item=item, idempotency_key=uuid.uuid4())
            self.orders.append(str(order.pk))

    def test_concurrent_submissions_of_one_signature_yield_exactly_one_success(self):
        from django.db import close_old_connections

        barrier = threading.Barrier(2)
        statuses = []
        errors = []
        status_lock = threading.Lock()

        def submit(order_id):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(self.buyer)
                barrier.wait(timeout=10)
                response = client.post(
                    reverse("marketplace:order-payment", args=(order_id, "creator")),
                    {"envelope_xdr": SIGNED_PAYMENT_VECTOR},
                    format="json",
                )
                with status_lock:
                    statuses.append(response.status_code)
            except Exception as error:  # pragma: no cover - diagnostics for the race test
                with status_lock:
                    errors.append(repr(error))
            finally:
                close_old_connections()

        pending = {"status": "pending", "success": None, "result_code": "", "ledger": None}
        with patch("apps.marketplace.services.submit_signed_envelope", return_value="PENDING"), \
                patch("apps.marketplace.services.confirmation_for_hash", return_value=pending):
            threads = [threading.Thread(target=submit, args=(order_id,)) for order_id in self.orders]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)

        self.assertEqual(errors, [])
        self.assertEqual(sorted(statuses), [status.HTTP_200_OK, status.HTTP_409_CONFLICT])
        self.assertEqual(OrderPayment.objects.exclude(tx_hash="").count(), 1)


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}},
    MARKETPLACE_LIVE_PAYMENTS=True,
    MARKETPLACE_ALLOW_SIMULATED_PURCHASES=False,
    MARKETPLACE_PLATFORM_FEE_BPS=0,
    MARKETPLACE_TREASURY_ADDRESS="",
    MARKETPLACE_RECONCILIATION_STALE_MINUTES=30,
    MARKETPLACE_RECONCILIATION_RECHECK_DAYS=7,
)
class ReconciliationTests(APITestCase):
    """A pass that compares the chain with the ledger and reports to admins."""

    def setUp(self):
        self.buyer = User.objects.create_user(phone_number="+66839935561", password="StrongPassword123")
        self.creator = User.objects.create_user(phone_number="+66839935562", password="StrongPassword123")
        WalletLink.objects.create(user=self.buyer, address=VALID_SOURCE)
        WalletLink.objects.create(user=self.creator, address=VALID_DESTINATION)
        self.item = DigitalItem.objects.create(
            creator=self.creator,
            kind=DigitalItem.Kind.STICKER_PACK,
            title="Recon pack",
            proposed_price_nsat=123_456_789,
            state=DigitalItem.State.APPROVED,
        )
        self.client.force_authenticate(self.buyer)

    def _order(self):
        return services.create_order(buyer=self.buyer, item=self.item, idempotency_key=uuid.uuid4())

    def _paid(self, order, tx_hash="a" * 64):
        """Record the settlement the checkout path would have produced."""
        now = timezone.now()
        OrderPayment.objects.filter(order=order).update(
            state=OrderPayment.State.CONFIRMED,
            tx_hash=tx_hash,
            submitted_at=int(now.timestamp()),
            confirmed_at=now,
            ledger=991,
        )
        order.state = MarketplaceOrder.State.PAID
        order.paid_at = now
        order.save(update_fields=["state", "paid_at"])
        return order

    def test_paid_order_missing_rights_is_repaired_and_reported(self):
        order = self._paid(self._order())

        run = reconciliation.run_reconciliation(check_chain=False)

        self.assertEqual(run.status, MarketplaceReconciliationRun.Status.COMPLETED)
        self.assertTrue(MarketplaceEntitlement.objects.filter(owner=self.buyer, item=self.item).exists())
        self.assertTrue(CreatorSale.objects.filter(order=order).exists())
        entitlement_issue = run.issues.get(code="order_missing_entitlement")
        self.assertTrue(entitlement_issue.repaired)
        self.assertEqual(entitlement_issue.severity, MarketplaceReconciliationIssue.Severity.CRITICAL)
        self.assertTrue(run.issues.get(code="order_missing_sale").repaired)
        self.assertEqual(run.repairs_applied, 2)
        self.assertTrue(MarketplaceAuditEvent.objects.filter(action="order.repaired").exists())

        # Once repaired, a second pass finds the books consistent.
        again = reconciliation.run_reconciliation(check_chain=False)
        self.assertEqual(again.issues_found, 0)
        self.assertEqual(again.repairs_applied, 0)

    def test_dry_run_reports_a_gap_without_changing_anything(self):
        self._paid(self._order())

        run = reconciliation.run_reconciliation(check_chain=False, dry_run=True)

        self.assertFalse(MarketplaceEntitlement.objects.exists())
        self.assertFalse(CreatorSale.objects.exists())
        issue = run.issues.get(code="order_missing_entitlement")
        self.assertFalse(issue.repaired)
        self.assertIn("dry run", issue.detail)
        self.assertEqual(run.repairs_applied, 0)
        self.assertTrue(run.summary.startswith("Dry run"))

    def test_paid_order_without_a_confirmed_transfer_is_critical_and_untouched(self):
        order = self._order()
        OrderPayment.objects.filter(order=order).update(
            tx_hash="e" * 64,
            submitted_at=int(timezone.now().timestamp()),
        )
        order.state = MarketplaceOrder.State.PAID
        order.paid_at = timezone.now()
        order.save(update_fields=["state", "paid_at"])
        services.ensure_settlement_records(order)

        run = reconciliation.run_reconciliation(check_chain=False)

        issue = run.issues.get(code="paid_without_confirmed_payment")
        self.assertEqual(issue.severity, MarketplaceReconciliationIssue.Severity.CRITICAL)
        self.assertFalse(issue.repaired)
        self.assertEqual(MarketplaceOrder.objects.get(pk=order.pk).state, MarketplaceOrder.State.PAID)

    def test_chain_confirmed_transfer_is_settled_by_reconciliation(self):
        order = self._order()
        OrderPayment.objects.filter(order=order).update(
            tx_hash="b" * 64,
            submitted_at=int(timezone.now().timestamp()),
        )
        verdict = {"status": "confirmed", "success": True, "result_code": "", "ledger": 4242}

        with patch("apps.marketplace.services.confirmation_for_hash", return_value=verdict):
            run = reconciliation.run_reconciliation()

        self.assertEqual(MarketplaceOrder.objects.get(pk=order.pk).state, MarketplaceOrder.State.PAID)
        self.assertTrue(MarketplaceEntitlement.objects.filter(order=order).exists())
        issue = run.issues.get(code="order_settled_late")
        self.assertTrue(issue.repaired)
        self.assertTrue(MarketplaceAuditEvent.objects.filter(action="order.paid").exists())

    def test_stalled_transfer_is_reported_without_closing_the_order(self):
        order = self._order()
        OrderPayment.objects.filter(order=order).update(
            tx_hash="c" * 64,
            submitted_at=int((timezone.now() - timedelta(hours=3)).timestamp()),
        )
        pending = {"status": "pending", "success": None, "result_code": "", "ledger": None}

        with patch("apps.marketplace.services.confirmation_for_hash", return_value=pending):
            run = reconciliation.run_reconciliation()

        issue = run.issues.get(code="payment_stalled")
        self.assertFalse(issue.repaired)
        self.assertEqual(MarketplaceOrder.objects.get(pk=order.pk).state, MarketplaceOrder.State.AWAITING_PAYMENT)
        self.assertFalse(MarketplaceEntitlement.objects.exists())

    def test_reorg_is_reported_and_granted_access_is_not_revoked(self):
        order = self._paid(self._order(), tx_hash="d" * 64)
        services.ensure_settlement_records(order)
        failed = {"status": "failed", "success": False, "result_code": "tx_failed", "ledger": None}

        with patch("apps.marketplace.services.confirmation_for_hash", return_value=failed):
            run = reconciliation.run_reconciliation()

        issue = run.issues.get(code="payment_no_longer_confirmed")
        self.assertEqual(issue.severity, MarketplaceReconciliationIssue.Severity.CRITICAL)
        self.assertFalse(issue.repaired)
        self.assertTrue(MarketplaceEntitlement.objects.filter(order=order, revoked_at__isnull=True).exists())

    def test_command_writes_a_report_and_can_fail_for_alerting(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        self._paid(self._order())
        output = StringIO()
        call_command("reconcile_marketplace", skip_chain_check=True, stdout=output)
        self.assertIn("repaired", output.getvalue())
        run = MarketplaceReconciliationRun.objects.get()
        self.assertEqual(run.source, MarketplaceReconciliationRun.Source.COMMAND)

        other = DigitalItem.objects.create(
            creator=self.creator,
            kind=DigitalItem.Kind.BADGE,
            title="Second pack",
            proposed_price_nsat=500,
            state=DigitalItem.State.APPROVED,
        )
        second = services.create_order(buyer=self.buyer, item=other, idempotency_key=uuid.uuid4())
        self._paid(second, tx_hash="f" * 64)
        with self.assertRaises(CommandError):
            call_command("reconcile_marketplace", skip_chain_check=True, fail_on_issues=True, stdout=StringIO())

    def test_admin_action_runs_a_pass_and_records_the_operator(self):
        from django.contrib.messages.storage.cookie import CookieStorage

        from .admin import MarketplaceReconciliationRunAdmin

        user = User.objects.create_user(
            phone_number="+66839935563", password="StrongPassword123", is_staff=True
        )
        request = RequestFactory().post("/admin/marketplace/marketplacereconciliationrun/")
        request.user = user
        setattr(request, "_messages", CookieStorage(request))

        MarketplaceReconciliationRunAdmin(MarketplaceReconciliationRun, AdminSite()).run_reconciliation_now(
            request, MarketplaceReconciliationRun.objects.none()
        )

        run = MarketplaceReconciliationRun.objects.get()
        self.assertEqual(run.source, MarketplaceReconciliationRun.Source.ADMIN)
        self.assertEqual(run.triggered_by, user)
        self.assertEqual(len(list(request._messages)), 1)

    def test_admins_can_read_the_run_and_issue_reports(self):
        operator = User.objects.create_user(
            phone_number="+66839935564", password="StrongPassword123", is_staff=True, is_superuser=True
        )
        self._paid(self._order())
        reconciliation.run_reconciliation(check_chain=False)
        self.client.force_authenticate(None)
        self.client.force_login(operator)

        runs = self.client.get(reverse("admin:marketplace_marketplacereconciliationrun_changelist"))
        issues = self.client.get(reverse("admin:marketplace_marketplacereconciliationissue_changelist"))

        self.assertEqual(runs.status_code, status.HTTP_200_OK)
        self.assertEqual(issues.status_code, status.HTTP_200_OK)
        self.assertContains(runs, "Marketplace reconciliation runs")
        self.assertContains(issues, "order_missing_entitlement")
