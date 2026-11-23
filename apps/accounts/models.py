from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone

from .managers import UserManager
from django.conf import settings
from django.db import models


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model for SatoshiCore Messenger.

    Authentication is performed using the user's phone number
    in E.164 format (e.g. +923130067082).
    """

    phone_number = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        help_text="Phone number in E.164 format (e.g. +923130067082)",
    )

    # Google subject is the stable identity key for migrated NSAT users. Email
    # is mutable and is deliberately not used as the account primary key.
    google_sub = models.CharField(max_length=255, unique=True, blank=True, null=True, default=None)
    legacy_id = models.CharField(max_length=255, unique=True, blank=True, null=True, default=None)

    # Optional, user-chosen public handle for friend discovery. It is set
    # once through PublicIDAPIView and is never used as the account PK.
    public_id = models.CharField(max_length=20, unique=True, blank=True, null=True, default=None)

    email = models.EmailField(
        blank=True,
        null=True,
    )

    is_deleted = models.BooleanField(default=False)

    is_verified = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)

    is_staff = models.BooleanField(default=False)

    date_joined = models.DateTimeField(
        default=timezone.now,
    )

    objects = UserManager()

    USERNAME_FIELD = "phone_number"

    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"
        ordering = ["-date_joined"]

    def __str__(self):
        return self.phone_number or self.email or f"User #{self.pk}"
class Profile(models.Model):
    """
    Stores additional information about a user.

    Authentication-related fields remain in the User model.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    display_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
        help_text="User's display name.",
    )

    profile_picture = models.ImageField(
        upload_to="profiles/",
        blank=True,
        null=True,
    )

    about = models.CharField(
        max_length=150,
        blank=True,
        default="Hey there! I'm using SatoshiCore.",
        help_text="User status or bio.",
    )

    # Optional unverified contact detail. It is separate from the account's
    # login phone and must never be used for authentication or discovery.
    contact_phone = models.CharField(max_length=20, blank=True, default="")

    last_seen = models.DateTimeField(
        default=timezone.now,
    )

    is_online = models.BooleanField(default=False)

    # Number of live WebSocket inbox connections (one per open tab/device).
    # ``is_online`` is derived from this counter so closing one of several
    # tabs no longer marks the user offline.
    active_connections = models.PositiveIntegerField(default=0)

    # -- Privacy (Settings > Privacy). Enforced server-side in
    # apps/accounts/privacy.py wherever profile data leaves the API.
    PRIVACY_EVERYONE = "everyone"
    PRIVACY_CONTACTS = "contacts"
    PRIVACY_NOBODY = "nobody"
    PRIVACY_CHOICES = (
        (PRIVACY_EVERYONE, "Everyone"),
        (PRIVACY_CONTACTS, "My contacts"),
        (PRIVACY_NOBODY, "Nobody"),
    )
    allow_id_search = models.BooleanField(default=True)
    allow_phone_search = models.BooleanField(default=True)
    allow_contact_discovery = models.BooleanField(
        default=False,
        help_text="Let verified accounts find this user through Google Contacts sync.",
    )
    ONLINE_EVERYONE = "everyone"
    ONLINE_SAME_AS_LAST_SEEN = "same_as_last_seen"
    ONLINE_CHOICES = (
        (ONLINE_EVERYONE, "Everyone"),
        (ONLINE_SAME_AS_LAST_SEEN, "Same as last seen"),
    )

    last_seen_privacy = models.CharField(max_length=10, choices=PRIVACY_CHOICES, default=PRIVACY_EVERYONE)
    online_privacy = models.CharField(max_length=20, choices=ONLINE_CHOICES, default=ONLINE_EVERYONE)
    photo_privacy = models.CharField(max_length=10, choices=PRIVACY_CHOICES, default=PRIVACY_EVERYONE)
    about_privacy = models.CharField(max_length=10, choices=PRIVACY_CHOICES, default=PRIVACY_EVERYONE)
    read_receipts = models.BooleanField(
        default=True,
        help_text="Send/receive blue ticks in private chats (groups always send them).",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "profiles"
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"

    def __str__(self):
        if self.display_name:
            return self.display_name
        return self.user.phone_number or self.user.email or f"User #{self.user_id}"




class Contact(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_contacts",
    )

    contact_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_by_contacts",
    )

    name = models.CharField(
        max_length=100,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        db_table = "contacts"
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "contact_user"],
                name="unique_saved_contact",
            ),
            models.CheckConstraint(
                condition=~models.Q(
                    owner=models.F("contact_user")
                ),
                name="contact_cannot_save_self",
            ),
        ]

    def __str__(self):
        return (
            f"{self.owner.phone_number} saved "
            f"{self.contact_user.phone_number}"
        )


class GoogleContactSyncState(models.Model):
    """Minimal per-user sync metadata; never stores an address book or OAuth token."""

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="google_contact_sync",
    )
    encrypted_sync_token = models.TextField(blank=True, default="")
    consented_at = models.DateTimeField(default=timezone.now)
    current_full_sync_id = models.UUIDField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "google_contact_sync_states"


class GoogleContactMatch(models.Model):
    """Only contact resource IDs and matched NSAT accounts are retained."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="google_contact_matches",
    )
    resource_name = models.CharField(max_length=512)
    matched_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="google_contact_matchers",
    )
    last_seen_full_sync_id = models.UUIDField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "google_contact_matches"
        constraints = [
            models.UniqueConstraint(fields=["owner", "resource_name"], name="unique_google_contact_match"),
            models.CheckConstraint(condition=~models.Q(owner=models.F("matched_user")), name="google_contact_not_self"),
        ]
        indexes = [models.Index(fields=["owner", "matched_user"], name="google_match_owner_user_idx")]

