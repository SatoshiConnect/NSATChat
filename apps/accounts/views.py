from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework import serializers
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from rest_framework_simplejwt.tokens import RefreshToken

from .models import Profile, Contact, User, GoogleContactMatch
from .utils import broadcast_presence_refresh, normalize_phone_variants, notify_profile_changed
from .serializers import (
    DeleteAccountSerializer,
    PrivacySettingsSerializer,
    LoginSerializer,
    ProfileSerializer,
    UserRegistrationSerializer,
    UserSerializer,
    LogoutSerializer,
)
from drf_spectacular.utils import (
    extend_schema,
    OpenApiResponse,
)

class RegisterAPIView(APIView):
    """
    Register a new user.
    """

    permission_classes = [AllowAny]
    # Brute-force protection: THROTTLE_AUTH requests/minute per IP.
    throttle_scope = "auth"

    @extend_schema(
        summary="Register User",
        request=UserRegistrationSerializer,
        description="""
        Register a new user account.

        Creates a new account using the provided information.
        """,
        responses={
            201: OpenApiResponse(
                description="User registered successfully.",
            ),
            400: OpenApiResponse(
                description="Validation error.",
            ),
        },
        tags=["Accounts"],
    )

    

    def post( self, request,) -> Response:

        serializer = UserRegistrationSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.save()
            # Return tokens so the client can sign the new user in immediately.
            refresh = RefreshToken.for_user(user)

            return Response(
                {
                    "message": "User registered successfully.",
                    "user": UserSerializer(user, context={"viewer": user}).data,
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


class LoginAPIView(APIView):
    """
    Authenticate a user and return JWT tokens.
    """

    permission_classes = [AllowAny]
    # Brute-force protection: THROTTLE_AUTH requests/minute per IP.
    throttle_scope = "auth"

    @extend_schema(
        summary="Login",
        request=LoginSerializer,
        description="""
        Authenticate a user and return JWT access and refresh tokens.
        """,
        responses={
            200: OpenApiResponse(
                description="Login successful.",
            ),
            400: OpenApiResponse(
                description="Invalid credentials.",
            ),
        },
        tags=["Accounts"],
    )

    def post( self, request,) -> Response:

        serializer = LoginSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.validated_data["user"]

            refresh = RefreshToken.for_user(user)

            return Response(
                {
                    "message": "Login successful.",
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                    "user": UserSerializer(user, context={"viewer": user}).data,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


@ensure_csrf_cookie
def google_login_config(request):
    """Expose the public GIS client ID and issue the CSRF cookie for login."""
    from django.conf import settings

    return JsonResponse({"client_id": settings.GOOGLE_CLIENT_ID, "csrf": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
class GoogleLoginAPIView(APIView):
    """Verify a Google ID token and issue the same JWT session as phone login."""

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        from django.conf import settings

        client_id = settings.GOOGLE_CLIENT_ID
        credential = request.data.get("credential")
        if not client_id or not isinstance(credential, str) or len(credential) > 8192:
            return Response({"detail": "Google sign-in is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            identity = id_token.verify_oauth2_token(
                credential,
                google_requests.Request(),
                audience=client_id,
            )
            subject = str(identity.get("sub") or "")
            email = str(identity.get("email") or "").strip().lower()
            email_verified = identity.get("email_verified") is True
            if not subject or not email or not email_verified:
                raise ValueError("Google identity is incomplete or unverified.")
        except Exception:
            return Response({"detail": "Google sign-in could not be verified. Please try again."}, status=status.HTTP_401_UNAUTHORIZED)

        user = User.objects.filter(google_sub=subject).first()
        if user is None:
            # Never silently merge accounts by email. Existing NSAT identities
            # are linked to their immutable Google subject by the migration.
            if User.objects.filter(email__iexact=email).exists():
                return Response(
                    {"detail": "This email belongs to an existing account that needs migration."},
                    status=status.HTTP_409_CONFLICT,
                )
            name = str(identity.get("name") or email.split("@", 1)[0]).strip()[:100]
            user = User.objects.create_user(
                phone_number=None,
                email=email,
                google_sub=subject,
                is_verified=True,
            )
            Profile.objects.update_or_create(user=user, defaults={"display_name": name})
        elif not user.is_active or user.is_deleted:
            return Response({"detail": "This account is unavailable."}, status=status.HTTP_403_FORBIDDEN)

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "message": "Login successful.",
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user, context={"viewer": user}).data,
            },
            status=status.HTTP_200_OK,
        )


class LogoutAPIView(APIView):
    """
    Logout a user by blacklisting the refresh token.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Logout",
        request=LogoutSerializer,
        description="""
        Logout the authenticated user.

        Invalidates the refresh token.
        """,
        responses={
            200: OpenApiResponse(
                description="Logout successful.",
            ),
            401: OpenApiResponse(
                description="Authentication required.",
            ),
        },
        tags=["Accounts"],
    )

    def post( self, request,) -> Response:
        try:
            refresh_token = request.data.get("refresh")

            token = RefreshToken(refresh_token)

            token.blacklist()

            return Response(
                {
                    "message": "Logout successful."
                },
                status=status.HTTP_200_OK,
            )

        except Exception:
            return Response(
                {
                    "error": "Invalid refresh token."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


class MeAPIView(APIView):
    """
    Return the currently authenticated user.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Current User",
        description="""
        Retrieve the authenticated user's profile.
        """,
        responses={
            200: UserSerializer,
            401: OpenApiResponse(
                description="Authentication required.",
            ),
        },
        tags=["Accounts"],
    )

    def get(self, request):
        serializer = UserSerializer(request.user, context={"request": request})

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class UpdateProfileAPIView(APIView):
    """
    Update the authenticated user's profile.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Update Profile",
        request=ProfileSerializer,
        description="""
        Update the authenticated user's profile.
        """,
        responses={
            200: OpenApiResponse(
                description="Profile updated successfully.",
            ),
            400: OpenApiResponse(
                description="Validation error.",
            ),
        },
        tags=["Accounts"],
    )

    def patch(self, request):
        profile = request.user.profile
        remove_picture = str(request.data.get("remove_picture", "")).lower() in ("1", "true", "on", "yes")
        data = {
            key: request.data.get(key)
            for key in ("display_name", "about", "profile_picture")
            if key in request.data
        }

        serializer = ProfileSerializer(
            profile,
            data=data,
            partial=True,
        )

        new_email = None
        if "email" in request.data:
            new_email = str(request.data.get("email") or "").strip().lower()
            if new_email:
                try:
                    validate_email(new_email)
                except DjangoValidationError:
                    return Response({"email": ["Enter a valid email address."]}, status=status.HTTP_400_BAD_REQUEST)
                taken = User.objects.filter(email__iexact=new_email).exclude(pk=request.user.pk).exists()
                if taken:
                    return Response({"email": ["This email is already used by another account."]}, status=status.HTTP_400_BAD_REQUEST)

        if serializer.is_valid():
            if new_email is not None:
                request.user.email = new_email or None
                request.user.save(update_fields=["email"])
            if remove_picture and profile.profile_picture:
                profile.profile_picture.delete(save=False)
                profile.profile_picture = None
            serializer.save()
            notify_profile_changed(request.user)

            return Response(
                {
                    "message": "Profile updated successfully.",
                    "profile": serializer.data,
                    "user": UserSerializer(request.user, context={"request": request}).data,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

class ContactSerializer(serializers.ModelSerializer):
    contact_user = UserSerializer(read_only=True)
    phone_number = serializers.CharField(write_only=True, required=False)
    public_id = serializers.CharField(write_only=True, required=False)
    suggested_user_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = Contact
        fields = ("id", "name", "contact_user", "phone_number", "public_id", "suggested_user_id", "created_at")
        read_only_fields = ("id", "contact_user", "created_at")

    @staticmethod
    def _phone_variants(value):
        """Resolve common local/international formats to the account's stored phone."""
        return normalize_phone_variants(value)

    def validate(self, attrs):
        request = self.context["request"]
        if self.instance is None or "phone_number" in attrs or "public_id" in attrs or "suggested_user_id" in attrs:
            suggested_user_id = attrs.pop("suggested_user_id", None)
            public_id = str(attrs.pop("public_id", "")).strip().lower().removeprefix("@")
            phone = str(attrs.get("phone_number", "")).strip()
            if suggested_user_id is not None:
                target = User.objects.filter(
                    pk=suggested_user_id,
                    is_active=True,
                    is_deleted=False,
                ).select_related("profile").first()
                if target and not (
                    Contact.objects.filter(owner=target, contact_user=request.user).exists()
                    or GoogleContactMatch.objects.filter(owner=request.user, matched_user=target).exists()
                ):
                    target = None
                if not target:
                    raise serializers.ValidationError({"suggested_user_id": "This account is not available as a suggestion."})
            elif public_id:
                target = User.objects.filter(public_id=public_id, is_active=True, is_deleted=False).select_related("profile").first()
                if not target or not target.profile.allow_id_search:
                    raise serializers.ValidationError({"public_id": "No account was found for that ID."})
            else:
                variants = self._phone_variants(phone)
                if not variants:
                    raise serializers.ValidationError({"phone_number": "Phone number or public ID is required."})
                target = User.objects.filter(phone_number__in=variants, is_active=True, is_deleted=False, profile__allow_phone_search=True).order_by("id").first()
            if target is None:
                raise serializers.ValidationError({"phone_number": "No active SatoshiCore account was found for this number. Try the number with country code, e.g. +923001234567."})
            if target.pk == request.user.pk:
                raise serializers.ValidationError({"phone_number": "You cannot add yourself as a contact."})
            duplicates = Contact.objects.filter(owner=request.user, contact_user=target)
            if self.instance is not None:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError({"phone_number": "This contact is already saved."})
            attrs["contact_user_obj"] = target
        return attrs

    def create(self, validated_data):
        target = validated_data.pop("contact_user_obj")
        validated_data.pop("phone_number", None)
        validated_data.pop("public_id", None)
        validated_data.pop("suggested_user_id", None)
        return Contact.objects.create(owner=self.context["request"].user, contact_user=target, **validated_data)

    def update(self, instance, validated_data):
        target = validated_data.pop("contact_user_obj", None)
        validated_data.pop("phone_number", None)
        validated_data.pop("public_id", None)
        validated_data.pop("suggested_user_id", None)
        if target is not None:
            instance.contact_user = target
        if "name" in validated_data:
            instance.name = validated_data["name"]
        instance.save()
        return instance


def _notify_contacts_changed(user):
    """Keep every open tab of the owner in sync after a contact change."""
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        f"chat_inbox_{user.pk}",
        {"type": "inbox.contacts_changed"},
    )


class ContactListCreateAPIView(ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ContactSerializer
    throttle_scope = "auth"

    def perform_create(self, serializer):
        serializer.save()
        _notify_contacts_changed(self.request.user)

    def get_queryset(self):
        return Contact.objects.filter(owner=self.request.user).select_related("contact_user", "contact_user__profile").order_by("name", "contact_user__phone_number")


class ContactDetailAPIView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ContactSerializer

    def perform_update(self, serializer):
        serializer.save()
        _notify_contacts_changed(self.request.user)

    def perform_destroy(self, instance):
        instance.delete()
        _notify_contacts_changed(self.request.user)

    def get_queryset(self):
        return Contact.objects.filter(owner=self.request.user).select_related("contact_user", "contact_user__profile")


class ContactSuggestionsAPIView(APIView):
    """Accounts that already saved the current user, like friend recommendations."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        already_saved = Contact.objects.filter(owner=request.user).values_list("contact_user_id", flat=True)
        users = (
            User.objects.filter(saved_contacts__contact_user=request.user, is_active=True, is_deleted=False)
            .exclude(pk=request.user.pk)
            .exclude(pk__in=already_saved)
            .select_related("profile")
            .distinct()
            .order_by("profile__display_name", "id")[:50]
        )
        return Response(UserSerializer(users, many=True, context={"request": request}).data)


class ContactSyncAPIView(APIView):
    """Match contacts explicitly selected by the user and save matching accounts."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    def post(self, request):
        entries = request.data.get("contacts", [])
        if not isinstance(entries, list) or len(entries) > 100:
            return Response({"detail": "Choose up to 100 contacts at a time."}, status=status.HTTP_400_BAD_REQUEST)
        matched = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            variants = normalize_phone_variants(entry.get("phone", ""))
            if not variants:
                continue
            user = (
                User.objects.filter(phone_number__in=variants, is_active=True, is_deleted=False, profile__allow_phone_search=True)
                .exclude(pk=request.user.pk)
                .select_related("profile")
                .first()
            )
            if user:
                matched[user.pk] = (user, str(entry.get("name") or "").strip()[:100])
        created = []
        for user, name in matched.values():
            contact, was_created = Contact.objects.get_or_create(owner=request.user, contact_user=user, defaults={"name": name})
            if was_created:
                created.append(contact)
        if created:
            _notify_contacts_changed(request.user)
        return Response({
            "matched": len(matched),
            "added": len(created),
            "contacts": ContactSerializer(created, many=True, context={"request": request}).data,
        })


class AddGroupMemberContactAPIView(APIView):
    """Save a member only when both users are members of the submitted group."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    def post(self, request, pk):
        from apps.chat.choices import RoomType
        from apps.chat.models import Participant

        try:
            group_id = int(request.data.get("group_id"))
        except (TypeError, ValueError):
            return Response({"detail": "A valid shared group is required."}, status=status.HTTP_400_BAD_REQUEST)
        participants = Participant.objects.filter(
            room_id=group_id,
            room__room_type=RoomType.GROUP,
            room__is_active=True,
            user_id__in=[request.user.pk, pk],
        ).values_list("user_id", flat=True)
        if set(participants) != {int(request.user.pk), int(pk)} or int(pk) == int(request.user.pk):
            return Response({"detail": "You can only save a member from a group you share."}, status=status.HTTP_404_NOT_FOUND)
        target = User.objects.filter(pk=pk, is_active=True, is_deleted=False).select_related("profile").first()
        if not target:
            return Response({"detail": "That account is unavailable."}, status=status.HTTP_404_NOT_FOUND)
        contact, created = Contact.objects.get_or_create(
            owner=request.user,
            contact_user=target,
            defaults={"name": str(request.data.get("name") or "").strip()[:100]},
        )
        if created:
            _notify_contacts_changed(request.user)
        return Response(ContactSerializer(contact, context={"request": request}).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class AddChatParticipantContactAPIView(APIView):
    """Save a private-chat participant without requiring their phone number."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    def post(self, request, pk):
        from apps.chat.choices import RoomType
        from apps.chat.models import ChatRoom, Participant

        try:
            room_id = int(request.data.get("room_id"))
        except (TypeError, ValueError):
            return Response({"detail": "A valid private chat is required."}, status=status.HTTP_400_BAD_REQUEST)
        if int(pk) == int(request.user.pk):
            return Response({"detail": "You cannot add yourself as a contact."}, status=status.HTTP_400_BAD_REQUEST)

        room = ChatRoom.objects.filter(pk=room_id, room_type=RoomType.PRIVATE, is_active=True).first()
        if not room or not Participant.objects.filter(room=room, user=request.user).exists() or not Participant.objects.filter(room=room, user_id=pk).exists():
            return Response({"detail": "You can only save someone from a private chat you share."}, status=status.HTTP_404_NOT_FOUND)

        target = User.objects.filter(pk=pk, is_active=True, is_deleted=False).select_related("profile").first()
        if not target:
            return Response({"detail": "That account is unavailable."}, status=status.HTTP_404_NOT_FOUND)
        name = str(request.data.get("name") or "").strip()[:100]
        contact, created = Contact.objects.get_or_create(
            owner=request.user,
            contact_user=target,
            defaults={"name": name},
        )
        if created:
            _notify_contacts_changed(request.user)
        return Response(
            ContactSerializer(contact, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )



class UserLookupAPIView(APIView):
    """
    Find a registered account by its exact public ID, phone number, or verified email.

    Used by "New contact" and "New chat" to validate a number before saving
    it. Only exact (normalised) phone matches are returned so the endpoint
    cannot be used to enumerate the user directory.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    @extend_schema(summary="Look up an account by phone number", tags=["Accounts"])
    def get(self, request):
        public_id = str(request.query_params.get("public_id", "")).strip().lower().removeprefix("@")
        if public_id:
            user = (
                User.objects.filter(public_id=public_id, is_active=True, is_deleted=False, profile__allow_id_search=True)
                .select_related("profile")
                .first()
            )
            if user is None:
                return Response({"detail": "No active account uses that ID."}, status=status.HTTP_404_NOT_FOUND)
            saved = Contact.objects.filter(owner=request.user, contact_user=user).first()
            return Response({
                "user": UserSerializer(user, context={"request": request}).data,
                "is_self": user.pk == request.user.pk,
                "saved_contact": {"id": saved.id, "name": saved.name} if saved else None,
            })

        email = str(request.query_params.get("email", "")).strip().lower()
        if email:
            try:
                validate_email(email)
            except DjangoValidationError:
                return Response({"detail": "Enter a valid email address."}, status=status.HTTP_400_BAD_REQUEST)
            user = (
                User.objects.filter(email__iexact=email, is_verified=True, is_active=True, is_deleted=False)
                .select_related("profile")
                .first()
            )
            if user is None:
                return Response({"detail": "No verified account uses that email address."}, status=status.HTTP_404_NOT_FOUND)
            saved = Contact.objects.filter(owner=request.user, contact_user=user).first()
            return Response({
                "user": UserSerializer(user, context={"request": request}).data,
                "is_self": user.pk == request.user.pk,
                "saved_contact": {"id": saved.id, "name": saved.name} if saved else None,
            })

        phone = request.query_params.get("phone", "")
        variants = normalize_phone_variants(phone)
        if not variants:
            return Response({"detail": "Enter a phone number."}, status=status.HTTP_400_BAD_REQUEST)
        user = (
            User.objects.filter(phone_number__in=variants, is_active=True, is_deleted=False, profile__allow_phone_search=True)
            .select_related("profile")
            .order_by("id")
            .first()
        )
        if user is None:
            return Response(
                {"detail": "This phone number isn't on SatoshiCore."},
                status=status.HTTP_404_NOT_FOUND,
            )
        saved = Contact.objects.filter(owner=request.user, contact_user=user).first()
        return Response({
            "user": UserSerializer(user, context={"request": request}).data,
            "is_self": user.pk == request.user.pk,
            "saved_contact": {"id": saved.id, "name": saved.name} if saved else None,
        })


class PublicIDAPIView(APIView):
    """Let an account claim one optional, immutable public discovery ID."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    def post(self, request):
        import re
        from django.db import IntegrityError, transaction

        value = str(request.data.get("public_id", "")).strip().lower().removeprefix("@")
        if len(value) < 4 or len(value) > 20 or not re.fullmatch(r"[a-z0-9._-]+", value, flags=re.ASCII):
            return Response(
                {"detail": "Use 4–20 lowercase letters, numbers, periods, hyphens, or underscores."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if request.user.public_id:
            return Response({"detail": "Your ID is already set and cannot be changed."}, status=status.HTTP_409_CONFLICT)
        try:
            with transaction.atomic():
                updated = User.objects.filter(pk=request.user.pk, public_id__isnull=True).update(public_id=value)
        except IntegrityError:
            return Response({"detail": "That ID is already in use. Try another."}, status=status.HTTP_409_CONFLICT)
        if not updated:
            request.user.refresh_from_db(fields=["public_id"])
            return Response({"detail": "Your ID is already set and cannot be changed."}, status=status.HTTP_409_CONFLICT)
        request.user.refresh_from_db()
        return Response(UserSerializer(request.user, context={"request": request}).data, status=status.HTTP_200_OK)


class UserCommonGroupsAPIView(APIView):
    """Groups shared by the authenticated user and another user."""

    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Groups in common with a user", tags=["Accounts"])
    def get(self, request, pk):
        from apps.chat.choices import RoomType
        from apps.chat.models import ChatRoom, Participant

        rooms = list(
            ChatRoom.objects.filter(
                room_type=RoomType.GROUP,
                is_active=True,
                participants__user=request.user,
            )
            .filter(participants__user_id=pk)
            .distinct()
            .order_by("name")
        )
        saved_names = dict(
            Contact.objects.filter(owner=request.user).values_list("contact_user_id", "name")
        )
        members_by_room = {}
        for participant in (
            Participant.objects.filter(room__in=rooms)
            .select_related("user", "user__profile")
            .order_by("joined_at")
        ):
            members_by_room.setdefault(participant.room_id, []).append(participant.user)

        data = []
        for room in rooms:
            members = members_by_room.get(room.id, [])
            names = []
            for member in members:
                if member.pk == request.user.pk:
                    names.append("You")
                    continue
                profile = getattr(member, "profile", None)
                names.append(
                    (saved_names.get(member.pk) or "").strip()
                    or (getattr(profile, "display_name", "") or "").strip()
                    or member.phone_number
                )
            data.append({
                "id": room.id,
                "name": room.name,
                "photo": room.photo.url if room.photo else None,
                "participants_count": len(members),
                "member_names": names,
            })
        return Response(data)



class PrivacySettingsAPIView(APIView):
    """Settings > Privacy: last seen & online, profile photo, about, read receipts."""

    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Privacy settings", responses={200: PrivacySettingsSerializer}, tags=["Accounts"])
    def get(self, request):
        return Response(PrivacySettingsSerializer(request.user.profile).data)

    @extend_schema(
        summary="Update privacy settings",
        request=PrivacySettingsSerializer,
        responses={200: PrivacySettingsSerializer},
        tags=["Accounts"],
    )
    def patch(self, request):
        profile = request.user.profile
        serializer = PrivacySettingsSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Everyone who can see this user refreshes names/photos/about, and
        # gets presence re-filtered for them.
        notify_profile_changed(request.user)
        broadcast_presence_refresh(request.user)
        return Response(PrivacySettingsSerializer(profile).data)


class DeleteAccountAPIView(APIView):
    """Settings > Account > Delete account (confirm with phone number + password)."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    @extend_schema(summary="Delete my account", request=DeleteAccountSerializer, tags=["Accounts"])
    def post(self, request):
        from .deletion import delete_account

        serializer = DeleteAccountSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        delete_account(request.user)
        return Response({"message": "Your account was deleted."}, status=status.HTTP_200_OK)
