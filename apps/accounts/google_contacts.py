"""Consent-based Google Contacts discovery endpoints.

Google access tokens stay in the browser. The API processes phone/email
candidates in memory and persists only matched account IDs, Google resource
IDs, and an encrypted People API sync cursor.
"""

import base64
import hashlib
import re
import uuid

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.db.models.functions import Lower
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import GoogleContactMatch, GoogleContactSyncState, User
from .serializers import UserSerializer

_E164 = re.compile(r"^\+[1-9]\d{1,14}$")
_RESOURCE_NAME = re.compile(r"^people/[A-Za-z0-9._:-]{1,500}$")


def _cipher():
    # A purpose-derived key keeps the cursor confidential at rest and avoids
    # another production secret. SECRET_KEY must remain stable for token reuse.
    digest = hashlib.sha256((settings.SECRET_KEY + ":google-contact-sync").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _safe_match_user(user, request):
    data = UserSerializer(user, context={"request": request}).data
    # Contact sync should identify a member, not disclose their account email
    # or phone number as a side effect of matching.
    return {
        "id": data["id"],
        "public_id": data.get("public_id"),
        "profile": data.get("profile"),
    }


class GoogleContactSyncAPIView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "contact_sync"

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not settings.FEATURE_FLAGS["google_contacts_sync"]:
            from rest_framework.exceptions import NotFound

            raise NotFound()

    def get(self, request):
        state = GoogleContactSyncState.objects.filter(owner=request.user).first()
        sync_token = ""
        if state and state.encrypted_sync_token:
            try:
                sync_token = _cipher().decrypt(state.encrypted_sync_token.encode()).decode()
            except (InvalidToken, ValueError):
                # A secret rotation invalidates the cursor; next run performs
                # a fresh paginated sync instead of failing the whole feature.
                sync_token = ""
        matches = (
            User.objects.filter(
                google_contact_matchers__owner=request.user,
                is_active=True,
                is_deleted=False,
                is_verified=True,
                profile__allow_contact_discovery=True,
            )
            .select_related("profile")
            .distinct()
            .order_by("profile__display_name", "id")[:5000]
        )
        return Response({
            "connected": state is not None,
            "sync_token": sync_token,
            "matches": [_safe_match_user(user, request) for user in matches],
            "updated_at": state.updated_at if state else None,
        })

    @transaction.atomic
    def post(self, request):
        state = GoogleContactSyncState.objects.select_for_update().filter(owner=request.user).first()
        if request.data.get("consent_accepted") is True:
            if state is None:
                state = GoogleContactSyncState.objects.create(owner=request.user)

        if state is None:
            return Response({"detail": "Accept the contact discovery notice before syncing."}, status=status.HTTP_400_BAD_REQUEST)

        contacts = request.data.get("contacts", [])
        deleted_names = request.data.get("deleted_resource_names", [])
        if not isinstance(contacts, list) or len(contacts) > 1000:
            return Response({"detail": "Sync up to 1,000 changed contacts per request."}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(deleted_names, list) or len(deleted_names) > 1000:
            return Response({"detail": "Too many deleted contacts in one request."}, status=status.HTTP_400_BAD_REQUEST)

        full_sync = request.data.get("full_sync") is True
        run_id = None
        if full_sync:
            try:
                run_id = uuid.UUID(str(request.data.get("full_sync_id")))
            except (ValueError, TypeError, AttributeError):
                return Response({"detail": "A valid full sync ID is required."}, status=status.HTTP_400_BAD_REQUEST)
            if state.current_full_sync_id not in (None, run_id):
                return Response({"detail": "Another full sync is in progress. Start again."}, status=status.HTTP_409_CONFLICT)
            if state.current_full_sync_id is None:
                state.current_full_sync_id = run_id
                state.save(update_fields=["current_full_sync_id", "updated_at"])

        for resource_name in deleted_names:
            if not isinstance(resource_name, str) or not _RESOURCE_NAME.fullmatch(resource_name):
                return Response({"detail": "Invalid Google contact reference."}, status=status.HTTP_400_BAD_REQUEST)
            GoogleContactMatch.objects.filter(owner=request.user, resource_name=resource_name).delete()

        normalized_entries = []
        phone_numbers = set()
        email_addresses = set()
        for item in contacts:
            if not isinstance(item, dict):
                return Response({"detail": "Invalid Google contact entry."}, status=status.HTTP_400_BAD_REQUEST)
            resource_name = item.get("resource_name")
            phones = item.get("phones", [])
            emails = item.get("emails", [])
            deleted = item.get("deleted") is True
            if not isinstance(resource_name, str) or not _RESOURCE_NAME.fullmatch(resource_name):
                return Response({"detail": "Invalid Google contact reference."}, status=status.HTTP_400_BAD_REQUEST)
            if not isinstance(phones, list) or len(phones) > 20 or not isinstance(emails, list) or len(emails) > 20:
                return Response({"detail": "Invalid Google contact fields."}, status=status.HTTP_400_BAD_REQUEST)
            phone_values = {value.strip() for value in phones if isinstance(value, str) and _E164.fullmatch(value.strip())}
            email_values = {value.strip().lower() for value in emails if isinstance(value, str) and len(value) <= 254 and "@" in value}
            phone_numbers.update(phone_values)
            email_addresses.update(email_values)
            normalized_entries.append((resource_name, phone_values, email_values, deleted))

        by_phone = {}
        by_email = {}
        eligible = User.objects.filter(
            is_active=True,
            is_deleted=False,
            is_verified=True,
            profile__allow_contact_discovery=True,
        ).exclude(pk=request.user.pk)
        if phone_numbers:
            by_phone = {
                user.phone_number: user
                for user in eligible.filter(phone_number__in=phone_numbers).select_related("profile")
                if user.phone_number
            }
        if email_addresses:
            by_email = {
                email: user
                for email, user in eligible.annotate(contact_email=Lower("email"))
                .filter(contact_email__in=email_addresses)
                .select_related("profile")
                .values_list("contact_email", "id")
            }
            user_ids = set(by_email.values())
            email_users = User.objects.filter(pk__in=user_ids).select_related("profile")
            users_by_id = {user.pk: user for user in email_users}
            by_email = {email: users_by_id[user_id] for email, user_id in by_email.items()}

        for resource_name, phones, emails, deleted in normalized_entries:
            match = None
            if not deleted:
                match = next((by_phone[number] for number in phones if number in by_phone), None)
                if match is None:
                    match = next((by_email[email] for email in emails if email in by_email), None)
            if match is None:
                GoogleContactMatch.objects.filter(owner=request.user, resource_name=resource_name).delete()
                continue
            GoogleContactMatch.objects.update_or_create(
                owner=request.user,
                resource_name=resource_name,
                defaults={
                    "matched_user": match,
                    "last_seen_full_sync_id": run_id if full_sync else None,
                },
            )

        if request.data.get("complete") is True:
            sync_token = request.data.get("sync_token")
            if not isinstance(sync_token, str) or not sync_token or len(sync_token) > 8192:
                return Response({"detail": "Google did not return a valid sync cursor."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                state.encrypted_sync_token = _cipher().encrypt(sync_token.encode()).decode()
            except Exception:
                return Response({"detail": "The contact sync cursor could not be saved securely."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            if full_sync:
                GoogleContactMatch.objects.filter(owner=request.user).exclude(last_seen_full_sync_id=run_id).delete()
                state.current_full_sync_id = None
            state.save(update_fields=["encrypted_sync_token", "current_full_sync_id", "updated_at"])

        return Response({"processed": len(normalized_entries), "connected": True})

    def delete(self, request):
        GoogleContactMatch.objects.filter(owner=request.user).delete()
        GoogleContactSyncState.objects.filter(owner=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
