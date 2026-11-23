from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Contact, User
from apps.chat.choices import RoomType
from apps.chat.models import ChatRoom, Participant


class FriendDiscoveryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(phone_number="+66811110000", password="StrongPass123!")
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def test_public_id_and_phone_search_respect_privacy_controls(self):
        target = User.objects.create_user(
            phone_number="+66811110001",
            password="StrongPass123!",
            public_id="find-me-1",
        )
        id_result = self.client.get("/api/accounts/users/lookup/", {"public_id": "find-me-1"})
        phone_result = self.client.get("/api/accounts/users/lookup/", {"phone": "+66811110001"})
        self.assertEqual(id_result.status_code, 200)
        self.assertEqual(phone_result.status_code, 200)

        target.profile.allow_id_search = False
        target.profile.allow_phone_search = False
        target.profile.save(update_fields=["allow_id_search", "allow_phone_search"])
        self.assertEqual(self.client.get("/api/accounts/users/lookup/", {"public_id": "find-me-1"}).status_code, 404)
        self.assertEqual(self.client.get("/api/accounts/users/lookup/", {"phone": "+66811110001"}).status_code, 404)

    def test_public_id_add_does_not_require_phone_number(self):
        target = User.objects.create_user(
            phone_number=None,
            password="StrongPass123!",
            google_sub="google-sub-without-phone",
            public_id="id-only-friend",
        )

        response = self.client.post(
            "/api/accounts/contacts/",
            {"name": "ID friend", "public_id": "@id-only-friend"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Contact.objects.filter(owner=self.owner, contact_user=target, name="ID friend").exists())

    def test_contact_sync_adds_only_users_who_allow_phone_search(self):
        allowed = User.objects.create_user(phone_number="+66811110002", password="StrongPass123!")
        hidden = User.objects.create_user(phone_number="+66811110003", password="StrongPass123!")
        hidden.profile.allow_phone_search = False
        hidden.profile.save(update_fields=["allow_phone_search"])

        response = self.client.post("/api/accounts/contacts/sync/", {
            "contacts": [
                {"name": "Allowed friend", "phone": allowed.phone_number},
                {"name": "Hidden friend", "phone": hidden.phone_number},
            ],
        }, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["added"], 1)
        self.assertTrue(Contact.objects.filter(owner=self.owner, contact_user=allowed, name="Allowed friend").exists())
        self.assertFalse(Contact.objects.filter(owner=self.owner, contact_user=hidden).exists())

    def test_recommendation_can_be_added_only_if_that_user_saved_me(self):
        other = User.objects.create_user(phone_number="+66811110004", password="StrongPass123!", public_id="friend-004")
        Contact.objects.create(owner=other, contact_user=self.owner)
        response = self.client.get("/api/accounts/contacts/suggestions/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [other.id])

        added = self.client.post("/api/accounts/contacts/", {"suggested_user_id": other.id}, format="json")
        self.assertEqual(added.status_code, 201)
        self.assertTrue(Contact.objects.filter(owner=self.owner, contact_user=other).exists())

        arbitrary = User.objects.create_user(phone_number="+66811110005", password="StrongPass123!")
        rejected = self.client.post("/api/accounts/contacts/", {"suggested_user_id": arbitrary.id}, format="json")
        self.assertEqual(rejected.status_code, 400)

    def test_group_member_can_be_added_only_from_a_shared_group(self):
        member = User.objects.create_user(phone_number="+66811110006", password="StrongPass123!")
        group = ChatRoom.objects.create(created_by=self.owner, room_type=RoomType.GROUP, name="Shared group")
        Participant.objects.create(room=group, user=self.owner)
        Participant.objects.create(room=group, user=member)
        unrelated = ChatRoom.objects.create(created_by=self.owner, room_type=RoomType.GROUP, name="Other group")

        added = self.client.post(f"/api/accounts/users/{member.id}/add-contact-from-group/", {"group_id": group.id}, format="json")
        rejected = self.client.post(f"/api/accounts/users/{member.id}/add-contact-from-group/", {"group_id": unrelated.id}, format="json")

        self.assertEqual(added.status_code, 201)
        self.assertEqual(rejected.status_code, 404)
        self.assertTrue(Contact.objects.filter(owner=self.owner, contact_user=member).exists())

    def test_private_chat_participant_can_be_added_without_phone_number(self):
        member = User.objects.create_user(phone_number="+66811110007", password="StrongPass123!")
        room = ChatRoom.objects.create(created_by=self.owner, room_type=RoomType.PRIVATE)
        Participant.objects.create(room=room, user=self.owner)
        Participant.objects.create(room=room, user=member)

        response = self.client.post(
            f"/api/accounts/users/{member.id}/add-contact-from-chat/",
            {"room_id": room.id, "name": "Chat friend"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["contact_user"]["id"], member.id)
        self.assertTrue(Contact.objects.filter(owner=self.owner, contact_user=member, name="Chat friend").exists())

    def test_cannot_add_account_by_id_without_shared_private_chat(self):
        member = User.objects.create_user(phone_number="+66811110008", password="StrongPass123!")
        unrelated = ChatRoom.objects.create(created_by=self.owner, room_type=RoomType.PRIVATE)
        Participant.objects.create(room=unrelated, user=self.owner)

        response = self.client.post(
            f"/api/accounts/users/{member.id}/add-contact-from-chat/",
            {"room_id": unrelated.id, "name": "Unverified"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Contact.objects.filter(owner=self.owner, contact_user=member).exists())
