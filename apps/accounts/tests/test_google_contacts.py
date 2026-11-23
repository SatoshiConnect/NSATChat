import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Contact, GoogleContactMatch, GoogleContactSyncState, Profile, User


class GoogleContactsSyncTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(phone_number="+14155550100", password="StrongPass123!")
        self.client.force_authenticate(self.owner)
        self.match = User.objects.create_user(
            phone_number="+14155550101",
            email="friend@example.com",
            password="StrongPass123!",
            is_verified=True,
            public_id="friend_01",
        )
        self.hidden = User.objects.create_user(
            phone_number="+14155550102",
            email="hidden@example.com",
            password="StrongPass123!",
            is_verified=True,
            public_id="hidden_01",
        )
        Profile.objects.filter(user=self.match).update(allow_contact_discovery=True, display_name="Friend")

    def test_consent_required_and_only_opted_in_verified_accounts_match(self):
        response = self.client.post("/api/accounts/contacts/google/", {
            "contacts": [{"resource_name": "people/c1", "phones": ["+14155550101"]}],
        }, format="json")
        self.assertEqual(response.status_code, 400)

        response = self.client.post("/api/accounts/contacts/google/", {
            "consent_accepted": True,
            "contacts": [
                {"resource_name": "people/c1", "phones": ["+14155550101"]},
                {"resource_name": "people/c2", "phones": ["4155550102"]},
                {"resource_name": "people/c3", "phones": ["+14155550102"]},
            ],
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["processed"], 3)
        self.assertTrue(GoogleContactMatch.objects.filter(owner=self.owner, matched_user=self.match).exists())
        self.assertFalse(GoogleContactMatch.objects.filter(owner=self.owner, matched_user=self.hidden).exists())

    def test_verified_email_matches_without_disclosing_contact_fields(self):
        self.client.post("/api/accounts/contacts/google/", {"consent_accepted": True}, format="json")
        response = self.client.post("/api/accounts/contacts/google/", {
            "contacts": [{"resource_name": "people/c-email", "emails": ["FRIEND@example.com"]}],
        }, format="json")
        self.assertEqual(response.status_code, 200)
        results = self.client.get("/api/accounts/contacts/google/").data["matches"]
        self.assertEqual([item["id"] for item in results], [self.match.pk])
        self.assertNotIn("email", results[0])
        self.assertNotIn("phone_number", results[0])

    def test_full_sync_stores_encrypted_cursor_and_cleans_stale_matches(self):
        state = GoogleContactSyncState.objects.create(owner=self.owner)
        old = User.objects.create_user(phone_number="+14155550103", password="StrongPass123!", is_verified=True)
        GoogleContactMatch.objects.create(owner=self.owner, matched_user=old, resource_name="people/old")
        run_id = str(uuid.uuid4())
        response = self.client.post("/api/accounts/contacts/google/", {
            "full_sync": True,
            "full_sync_id": run_id,
            "contacts": [{"resource_name": "people/current", "emails": ["friend@example.com"]}],
            "complete": True,
            "sync_token": "private-next-sync-token",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        state.refresh_from_db()
        self.assertNotIn("private-next-sync-token", state.encrypted_sync_token)
        self.assertFalse(GoogleContactMatch.objects.filter(owner=self.owner, matched_user=old).exists())
        self.assertEqual(self.client.get("/api/accounts/contacts/google/").data["sync_token"], "private-next-sync-token")

    def test_match_authorizes_add_friend_and_disconnect_deletes_sync_data(self):
        self.client.post("/api/accounts/contacts/google/", {"consent_accepted": True}, format="json")
        self.client.post("/api/accounts/contacts/google/", {
            "contacts": [{"resource_name": "people/c1", "phones": ["+14155550101"]}],
        }, format="json")
        added = self.client.post("/api/accounts/contacts/", {"name": "Friend", "suggested_user_id": self.match.pk}, format="json")
        self.assertEqual(added.status_code, 201)
        self.assertTrue(Contact.objects.filter(owner=self.owner, contact_user=self.match).exists())

        removed = self.client.delete("/api/accounts/contacts/google/")
        self.assertEqual(removed.status_code, 204)
        self.assertFalse(GoogleContactMatch.objects.filter(owner=self.owner).exists())
        self.assertFalse(GoogleContactSyncState.objects.filter(owner=self.owner).exists())

    def test_member_opt_out_clears_existing_match_metadata(self):
        self.client.post("/api/accounts/contacts/google/", {"consent_accepted": True}, format="json")
        self.client.post("/api/accounts/contacts/google/", {
            "contacts": [{"resource_name": "people/c1", "phones": ["+14155550101"]}],
        }, format="json")
        target_client = APIClient()
        target_client.force_authenticate(self.match)
        response = target_client.patch("/api/accounts/privacy/", {"allow_contact_discovery": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GoogleContactMatch.objects.filter(matched_user=self.match).exists())
