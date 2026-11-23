from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User


@override_settings(GOOGLE_CLIENT_ID="nsat-web-client.apps.googleusercontent.com")
class GoogleLoginTests(TestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        config = self.client.get("/api/accounts/google/config/")
        self.csrf = config.json()["csrf"]

    def login(self, identity):
        with patch("apps.accounts.views.id_token.verify_oauth2_token", return_value=identity) as verify:
            response = self.client.post(
                "/api/accounts/google/login/",
                {"credential": "signed-google-id-token"},
                format="json",
                HTTP_X_CSRFTOKEN=self.csrf,
            )
        verify.assert_called_once()
        return response

    def test_google_subject_creates_passwordless_account_and_returns_tokens(self):
        response = self.login({
            "sub": "google-sub-1",
            "email": "person@example.com",
            "email_verified": True,
            "name": "Test Person",
        })
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(google_sub="google-sub-1")
        self.assertIsNone(user.phone_number)
        self.assertEqual(user.email, "person@example.com")
        self.assertEqual(user.profile.display_name, "Test Person")
        self.assertTrue(response.json()["access"])
        self.assertTrue(response.json()["refresh"])

    def test_same_google_subject_returns_the_existing_account(self):
        user = User.objects.create_user(
            phone_number=None,
            email="person@example.com",
            google_sub="google-sub-1",
            is_verified=True,
        )
        response = self.login({
            "sub": "google-sub-1",
            "email": "changed@example.com",
            "email_verified": True,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], user.id)
        self.assertEqual(User.objects.count(), 1)

    def test_email_match_never_silently_links_a_different_google_subject(self):
        User.objects.create_user(phone_number="+66812345678", email="person@example.com", password="StrongPass123!")
        response = self.login({
            "sub": "different-google-sub",
            "email": "person@example.com",
            "email_verified": True,
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(User.objects.count(), 1)

    def test_unverified_identity_is_rejected(self):
        response = self.login({
            "sub": "google-sub-1",
            "email": "person@example.com",
            "email_verified": False,
        })
        self.assertEqual(response.status_code, 401)
        self.assertFalse(User.objects.exists())

    def test_login_requires_csrf_token(self):
        client = APIClient(enforce_csrf_checks=True)
        with patch("apps.accounts.views.id_token.verify_oauth2_token") as verify:
            response = client.post(
                "/api/accounts/google/login/",
                {"credential": "signed-google-id-token"},
                format="json",
            )
        self.assertEqual(response.status_code, 403)
        verify.assert_not_called()

    def test_exact_verified_email_lookup_is_available_to_signed_in_users(self):
        owner = User.objects.create_user(phone_number="+66812345678", password="StrongPass123!")
        target = User.objects.create_user(
            phone_number=None,
            email="friend@example.com",
            google_sub="friend-google-sub",
            is_verified=True,
        )
        self.client.force_authenticate(user=owner)
        response = self.client.get("/api/accounts/users/lookup/", {"email": "FRIEND@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], target.id)

    def test_exact_email_lookup_does_not_expose_unverified_account_email(self):
        owner = User.objects.create_user(phone_number="+66812345678", password="StrongPass123!")
        User.objects.create_user(phone_number="+66812345679", email="friend@example.com", password="StrongPass123!")
        self.client.force_authenticate(user=owner)
        response = self.client.get("/api/accounts/users/lookup/", {"email": "friend@example.com"})
        self.assertEqual(response.status_code, 404)

    def test_exact_public_id_lookup_returns_active_account(self):
        owner = User.objects.create_user(phone_number="+66812345678", password="StrongPass123!")
        target = User.objects.create_user(phone_number="+66812345679", email="friend@example.com", is_verified=True, public_id="friend.id")
        self.client.force_authenticate(user=owner)
        response = self.client.get("/api/accounts/users/lookup/", {"public_id": "@FRIEND.ID"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], target.id)
        self.assertEqual(response.json()["user"]["public_id"], "friend.id")
        self.assertFalse(response.json()["is_self"])

    def test_public_id_can_only_be_set_once_and_obeys_line_style_characters(self):
        owner = User.objects.create_user(phone_number="+66812345678", password="StrongPass123!")
        self.client.force_authenticate(user=owner)

        invalid_response = self.client.post("/api/accounts/profile/public-id/", {"public_id": "User Name!"}, format="json")
        created_response = self.client.post("/api/accounts/profile/public-id/", {"public_id": "Migs.2026"}, format="json")
        change_response = self.client.post("/api/accounts/profile/public-id/", {"public_id": "another_id"}, format="json")

        self.assertEqual(invalid_response.status_code, 400)
        self.assertEqual(created_response.status_code, 200)
        self.assertEqual(created_response.json()["public_id"], "migs.2026")
        self.assertEqual(change_response.status_code, 409)

    def test_duplicate_public_id_is_rejected(self):
        owner = User.objects.create_user(phone_number="+66812345678", password="StrongPass123!")
        User.objects.create_user(phone_number="+66812345679", password="StrongPass123!", public_id="migs_2026")
        self.client.force_authenticate(user=owner)
        response = self.client.post("/api/accounts/profile/public-id/", {"public_id": "migs_2026"}, format="json")
        self.assertEqual(response.status_code, 409)
